"""Tests for local text processing engine."""

import pytest
from tucknote.transcription.processor import RuleBasedTextProcessor, get_default_text_processor


def test_rule_based_processor_removes_fillers():
    proc = RuleBasedTextProcessor()
    text = "Ich denke ähm dass die api halt erneuert werden muss"
    res = proc.process(text)
    assert res.success is True
    assert "ähm" not in res.text
    assert "halt" not in res.text
    assert "API" in res.text
    assert res.text.startswith("Ich denke")


def test_rule_based_processor_removes_duplicates():
    proc = RuleBasedTextProcessor()
    text = "the the client should retry the connection"
    res = proc.process(text)
    assert res.success is True
    assert "the the" not in res.text
    assert "The client should retry the connection." == res.text


def test_rule_based_processor_normalizes_tech_terms():
    proc = RuleBasedTextProcessor()
    text = "open in vs code and push to github"
    res = proc.process(text)
    assert res.success is True
    assert "VS Code" in res.text
    assert "GitHub" in res.text


def test_rule_based_processor_empty():
    proc = RuleBasedTextProcessor()
    assert proc.process("").text == ""
    assert proc.process("   ").text == ""


def test_rule_based_processor_categorization():
    proc = RuleBasedTextProcessor()
    assert proc.process("Wir müssen den bug fixen").category == "Task"
    assert proc.process("Hier ist ein schwerer fehler im system").category == "Bug"
    assert proc.process("Vielleicht könnte man das per overlay lösen").category == "Idea"
    assert proc.process("Das meeting war sehr informativ").category == "Note"


def test_default_processor_factory():
    proc = get_default_text_processor(engine="rules")
    assert proc is not None
    assert proc.processor_id == "rule-based-v1"

    proc_llm = get_default_text_processor(engine="llm", model_key="qwen2.5-0.5b")
    assert proc_llm is not None
    assert "local-llm" in proc_llm.processor_id


def test_local_llm_processor_empty():
    from tucknote.transcription.llm_processor import LocalLLMProcessor
    proc = LocalLLMProcessor()
    res = proc.process("")
    assert res.success is True
    assert res.text == ""
    assert res.category is None
    assert res.tags == []


def test_local_llm_processor_fallback(monkeypatch):
    from tucknote.transcription.llm_processor import LocalLLMProcessor
    proc = LocalLLMProcessor()
    # Force server ensure to fail to test fallback path
    monkeypatch.setattr(proc, "ensure_server", lambda: False)
    res = proc.process("Wir müssen den crash analysieren", context_app="Code.exe")
    assert res.success is True
    assert res.category == "Task" or res.category == "Bug"
    assert "crash" in res.text


def test_local_llm_processor_model_switch():
    from tucknote.transcription.llm_processor import LocalLLMProcessor
    proc = LocalLLMProcessor(model_key="qwen2.5-0.5b")
    assert proc.model_key == "qwen2.5-0.5b"
    proc.update_model("qwen2.5-1.5b")
    assert proc.model_key == "qwen2.5-1.5b"


def test_llm_model_size_and_deletion(tmp_path, monkeypatch):
    from tucknote.transcription import llm_processor

    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(llm_processor, "get_data_dir", lambda: tmp_path)

    # Initially not cached
    assert llm_processor.is_llm_model_cached("qwen2.5-0.5b") is False
    assert llm_processor.get_llm_model_size_mb("qwen2.5-0.5b") == 0.0

    # Create dummy model file
    model_path = llm_processor.get_llm_model_path("qwen2.5-0.5b")
    model_path.write_bytes(b"\x00" * (1024 * 1024 * 3))  # 3 MB

    assert llm_processor.is_llm_model_cached("qwen2.5-0.5b") is True
    assert llm_processor.get_llm_model_size_mb("qwen2.5-0.5b") >= 2.9

    # Delete
    deleted = llm_processor.delete_llm_model("qwen2.5-0.5b")
    assert deleted is True
    assert llm_processor.is_llm_model_cached("qwen2.5-0.5b") is False
    assert model_path.exists() is False

