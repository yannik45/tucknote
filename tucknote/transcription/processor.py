"""Local text processing engine to refine raw transcripts into cleaner text.

Improves punctuation, capitalization, removes accidental stuttering/filler words,
and normalizes common technical terms without altering or inventing factual statements.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger("tucknote")


@dataclass
class ProcessedTextResult:
    text: str
    processor_id: str
    success: bool
    error: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)


class TextProcessor(Protocol):
    """Protocol for text refinement engines."""

    def process(
        self,
        text: str,
        context_app: str | None = None,
        context_window: str | None = None,
        language: str | None = None,
    ) -> ProcessedTextResult:
        ...

    def stop(self) -> None:
        ...


class RuleBasedTextProcessor:
    """Fast, reliable, 100% local rule-based text normalizer."""

    PROCESSOR_ID = "rule-based-v1"

    @property
    def processor_id(self) -> str:
        return self.PROCESSOR_ID

    # Common spoken filler words
    GERMAN_FILLERS = [
        r"\b(ähm|äh|öhm|mhm|hm)\b",
        r"\bsozusagen\b(?=\s*,|\s*\.)?",
        r"\bhalt\b(?=\s*,|\s*\.)?",
    ]

    ENGLISH_FILLERS = [
        r"\b(uhm|um|uh|er|erm|ah)\b",
        r"\byou know\b(?=\s*,|\s*\.)?",
    ]

    # Technical term casings
    TECH_TERMS = {
        r"\bapi\b": "API",
        r"\bapis\b": "APIs",
        r"\bvs\s*code\b": "VS Code",
        r"\bvscode\b": "VS Code",
        r"\bgithub\b": "GitHub",
        r"\bgit\b": "Git",
        r"\bsqlite\b": "SQLite",
        r"\bsql\b": "SQL",
        r"\bui\b": "UI",
        r"\bux\b": "UX",
        r"\burl\b": "URL",
        r"\burls\b": "URLs",
        r"\bhttp\b": "HTTP",
        r"\bhttps\b": "HTTPS",
        r"\brest\b": "REST",
        r"\bjson\b": "JSON",
        r"\bpr\b": "PR",
        r"\bci\b": "CI",
        r"\bcd\b": "CD",
        r"\bmvp\b": "MVP",
        r"\bcli\b": "CLI",
        r"\bgui\b": "GUI",
        r"\bctypes\b": "ctypes",
        r"\bpyside\b": "PySide",
        r"\bwhisper\b": "Whisper",
        r"\btucknote\b": "Tucknote",
    }

    def process(
        self,
        text: str,
        context_app: str | None = None,
        context_window: str | None = None,
        language: str | None = None,
    ) -> ProcessedTextResult:
        if not text or not text.strip():
            return ProcessedTextResult(
                text="",
                processor_id=self.PROCESSOR_ID,
                success=True,
                category=None,
                tags=[],
            )

        cleaned = text.strip()

        # 1. Remove obvious fillers based on language
        fillers = self.GERMAN_FILLERS + self.ENGLISH_FILLERS
        for pattern in fillers:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        # 2. Remove accidental repeated words ("the the" -> "the", "und und" -> "und")
        cleaned = re.sub(r"\b(\w+)\s+\1\b", r"\1", cleaned, flags=re.IGNORECASE)

        # 3. Clean up multiple spaces & dangling punctuation
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s+([,.:;?!])", r"\1", cleaned)
        cleaned = re.sub(r"([,.:;?!])\1+", r"\1", cleaned)

        # 4. Capitalize first letter of sentences
        def cap_sentence(match):
            return match.group(1) + match.group(2).upper()

        cleaned = re.sub(r"(^|[.?!]\s+)([a-zäöü])", cap_sentence, cleaned)

        # 5. Fix common technical terminology casing
        for pattern, replacement in self.TECH_TERMS.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

        # 6. Ensure ending punctuation if sentence-like
        cleaned = cleaned.strip()
        if cleaned and not cleaned.endswith((".", "!", "?")):
            cleaned += "."

        # Heuristic classification for rule-based engine
        lower = cleaned.lower()
        if any(w in lower for w in ["todo", "task", "aufgabe", "muss ", "fixen", "erledigen", "implementieren"]):
            cat = "Task"
        elif any(w in lower for w in ["bug", "fehler", "crash", "kaputt", "problem", "error", "fail"]):
            cat = "Bug"
        elif any(w in lower for w in ["idee", "idea", "vielleicht", "könnte man", "feature", "überlegen"]):
            cat = "Idea"
        else:
            cat = "Note"

        return ProcessedTextResult(
            text=cleaned,
            processor_id=self.PROCESSOR_ID,
            success=True,
            category=cat,
            tags=[],
        )

    def stop(self) -> None:
        """No-op for rule-based processor."""
        pass


def get_default_text_processor(engine: str = "llm", model_key: str = "qwen2.5-0.5b") -> TextProcessor:
    """Return default text processor based on configured engine."""
    if engine == "llm":
        try:
            from tucknote.transcription.llm_processor import LocalLLMProcessor
            return LocalLLMProcessor(model_key=model_key)
        except Exception as e:
            logger.warning("Could not initialize LocalLLMProcessor: %s. Using rule-based fallback.", e)
            return RuleBasedTextProcessor()
    return RuleBasedTextProcessor()
