"""Local LLM-based text processor using embedded llama.cpp runtime.

Provides intelligent speech note refinement, grammar cleanup, contextual word correction,
automatic categorization (Task, Bug, Idea, Note), and topic tagging.
"""

from __future__ import annotations

import os
import sys
import json
import time
import zipfile
import io
import urllib.request
import urllib.error
import subprocess
import threading
import logging
from pathlib import Path

from tucknote.config import get_data_dir
from tucknote.transcription.processor import ProcessedTextResult, RuleBasedTextProcessor

logger = logging.getLogger("tucknote")

LLAMA_SERVER_PORT = 8089

MODELS = {
    "qwen2.5-0.5b": {
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size_mb": 398,
        "name": "Qwen 2.5 0.5B (Schnell, ~2-3s)",
    },
    "qwen2.5-1.5b": {
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_mb": 986,
        "name": "Qwen 2.5 1.5B (Sehr präzise, ~8-9s)",
    },
}

LLAMA_BIN_URL = "https://github.com/ggerganov/llama.cpp/releases/download/b3600/llama-b3600-bin-win-avx2-x64.zip"


def get_llm_model_path(model_key: str) -> Path | None:
    """Get the path to a downloaded GGUF LLM model file on disk."""
    if model_key not in MODELS:
        return None
    return get_data_dir() / "models" / MODELS[model_key]["filename"]


def is_llm_model_cached(model_key: str) -> bool:
    """Check if an LLM model GGUF file is already downloaded and present on disk."""
    path = get_llm_model_path(model_key)
    return path.exists() and path.stat().st_size > 1024 * 1024 if path else False


def get_llm_model_size_mb(model_key: str) -> float:
    """Return the disk size of the LLM model file in megabytes, or 0.0 if not downloaded."""
    path = get_llm_model_path(model_key)
    if not path or not path.exists():
        return 0.0
    return round(path.stat().st_size / (1024 * 1024), 1)



def delete_llm_model(model_key: str) -> bool:
    """Delete a downloaded LLM model GGUF file to reclaim disk space."""
    path = get_llm_model_path(model_key)
    if not path or not path.exists():
        return False
    try:
        logger.info("Deleting LLM model '%s' at %s...", model_key, path)
        path.unlink()
        return True
    except Exception as e:
        logger.error("Failed to delete LLM model '%s': %s", model_key, e)
        return False


class LocalLLMProcessor:
    """Manages an embedded, local llama-server instance for text refinement & classification."""

    def __init__(self, model_key: str = "qwen2.5-0.5b", port: int = LLAMA_SERVER_PORT):
        self.model_key = model_key if model_key in MODELS else "qwen2.5-0.5b"
        self.port = port
        self._server_proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._fallback = RuleBasedTextProcessor()
        self._is_starting = False

    @property
    def processor_id(self) -> str:
        return f"local-llm:{self.model_key}"

    def _get_bin_dir(self) -> Path:
        p = get_data_dir() / "bin" / "llama-cpp"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _get_models_dir(self) -> Path:
        p = get_data_dir() / "models"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _ensure_binaries(self) -> Path | None:
        """Ensure llama-server.exe exists, downloading portable runtime if missing."""
        bin_dir = self._get_bin_dir()
        server_exe = bin_dir / "llama-server.exe"
        if server_exe.exists():
            return server_exe

        logger.info("Downloading embedded llama.cpp runtime...")
        try:
            req = urllib.request.Request(LLAMA_BIN_URL, headers={"User-Agent": "tucknote"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(bin_dir)
            logger.info("llama.cpp runtime extracted to %s", bin_dir)
            return server_exe if server_exe.exists() else None
        except Exception as e:
            logger.error("Failed to download llama.cpp runtime: %s", e)
            return None

    def _ensure_model(self) -> Path | None:
        """Ensure model GGUF exists, downloading if missing."""
        info = MODELS.get(self.model_key)
        if not info:
            return None

        models_dir = self._get_models_dir()
        model_path = models_dir / info["filename"]
        if model_path.exists() and model_path.stat().st_size > 10_000_000:
            return model_path

        logger.info("Downloading local LLM model %s (~%d MB)...", self.model_key, info["size_mb"])
        try:
            req = urllib.request.Request(info["url"], headers={"User-Agent": "tucknote"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(model_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            logger.info("Model %s downloaded successfully.", self.model_key)
            return model_path
        except Exception as e:
            logger.error("Failed downloading model %s: %s", self.model_key, e)
            if model_path.exists():
                model_path.unlink()
            return None

    def _is_server_alive(self) -> bool:
        if not self._server_proc or self._server_proc.poll() is not None:
            return False
        try:
            url = f"http://127.0.0.1:{self.port}/health"
            with urllib.request.urlopen(url, timeout=1) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start_server_async(self) -> None:
        """Preload the server in the background."""
        threading.Thread(target=self.ensure_server, daemon=True).start()

    def ensure_server(self) -> bool:
        """Start llama-server.exe if not already active."""
        with self._lock:
            if self._is_server_alive():
                return True

            server_exe = self._ensure_binaries()
            if not server_exe or not server_exe.exists():
                logger.warning("llama-server.exe not available.")
                return False

            model_path = self._ensure_model()
            if not model_path or not model_path.exists():
                logger.warning("GGUF model not available.")
                return False

            if self._server_proc and self._server_proc.poll() is None:
                try:
                    self._server_proc.terminate()
                    self._server_proc.wait(timeout=2)
                except Exception:
                    pass

            cmd = [
                str(server_exe),
                "-m", str(model_path),
                "--port", str(self.port),
                "-c", "2048",
                "-t", "4",
                "-ngl", "0",
            ]

            logger.info("Starting local LLM server on port %d with %s...", self.port, self.model_key)
            try:
                self._server_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(self._get_bin_dir()),
                )
            except Exception as e:
                logger.error("Failed to launch llama-server: %s", e)
                return False

        # Wait for server ready (outside lock)
        for _ in range(40):
            time.sleep(0.25)
            if self._is_server_alive():
                logger.info("Local LLM server is ready.")
                return True

        logger.warning("Local LLM server failed to report healthy in time.")
        return False

    def update_model(self, model_key: str) -> None:
        """Change active model and restart server."""
        if model_key not in MODELS or model_key == self.model_key:
            return
        self.model_key = model_key
        self.stop()
        self.start_server_async()

    def process(
        self,
        text: str,
        context_app: str | None = None,
        context_window: str | None = None,
        language: str | None = None,
    ) -> ProcessedTextResult:
        """Refine text and categorize using local LLM, falling back to rule-based on failure."""
        cleaned_raw = text.strip()
        if not cleaned_raw:
            return ProcessedTextResult(
                text="",
                processor_id=self.processor_id,
                success=True,
                category=None,
                tags=[],
            )

        if not self.ensure_server():
            logger.info("LLM server unavailable; falling back to rule-based processing.")
            return self._fallback.process(cleaned_raw, context_app, context_window, language)

        system_prompt = (
            "Du bist ein intelligenter Assistent für Sprachnotizen.\n"
            "Deine Aufgabe: Analysiere das Transkript und den Kontext, wähle genau EINE Kategorie und vergib 1 bis 3 kurze Tags.\n\n"
            "Kategorien:\n"
            "- 'Task': Konkrete Aufgabe, Todo, Vorhaben, Bug fixen, etwas erledigen\n"
            "- 'Bug': Fehler, Problem, Crash, unerwartetes Verhalten, Defekt\n"
            "- 'Idea': Neue Idee, Feature-Vorschlag, Inspiration, Konzept\n"
            "- 'Note': Allgemeine Information, Notiz, Dokumentation, Gedanke\n\n"
            "Antworte AUSSCHLIESSLICH im folgenden JSON-Format:\n"
            "{\n"
            '  "category": "Task",\n'
            '  "tags": ["tag1", "tag2"]\n'
            "}"
        )

        ctx_parts = []
        if context_app:
            ctx_parts.append(context_app.replace(".exe", ""))
        if context_window:
            ctx_parts.append(context_window)
        ctx_str = " — ".join(ctx_parts) if ctx_parts else "None"

        user_content = f"Kontext: {ctx_str}\nTranskript: {cleaned_raw}"

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "max_tokens": 80,
        }

        chat_url = f"http://127.0.0.1:{self.port}/v1/chat/completions"
        req = urllib.request.Request(
            chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            content = data["choices"][0]["message"]["content"].strip()
            # Clean markdown codeblocks if LLM wrapped in ```json
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:].strip()

            parsed = json.loads(content.strip())
            category = str(parsed.get("category", "Note")).strip()
            if category not in ["Task", "Bug", "Idea", "Note"]:
                # Normalization
                lower_cat = category.lower()
                if "task" in lower_cat or "todo" in lower_cat:
                    category = "Task"
                elif "bug" in lower_cat or "error" in lower_cat:
                    category = "Bug"
                elif "idea" in lower_cat or "idee" in lower_cat:
                    category = "Idea"
                else:
                    category = "Note"

            tags = [str(t).strip() for t in parsed.get("tags", []) if t][:3]

            logger.info("LLM categorized note: [%s] tags=%s", category, tags)
            return ProcessedTextResult(
                text=cleaned_raw,
                processor_id=self.processor_id,
                success=True,
                category=category,
                tags=tags,
            )

        except Exception as exc:
            logger.warning("LLM processing inference error (%s); using rule-based fallback.", exc)
            return self._fallback.process(cleaned_raw, context_app, context_window, language)

    def stop(self) -> None:
        """Stop background llama-server process."""
        with self._lock:
            if self._server_proc and self._server_proc.poll() is None:
                logger.info("Stopping local LLM server process...")
                try:
                    self._server_proc.terminate()
                    self._server_proc.wait(timeout=3)
                except Exception:
                    try:
                        self._server_proc.kill()
                    except Exception:
                        pass
                self._server_proc = None
