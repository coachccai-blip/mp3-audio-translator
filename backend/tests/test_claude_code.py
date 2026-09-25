"""Traduction avec le compte Claude de l'utilisateur, via Claude Code installé localement (`claude -p`)."""
import json
import os
import stat
import sys

import pytest

from app.pipeline.translate import (ClaudeCodeTranslator, TranslationError, TranslationRequest, claude_code_path,
                                    run_claude_code)


def _fake_claude(tmp_path, monkeypatch, result: str, is_error: bool = False):
    """Faux exécutable `claude` : vérifie qu'aucune clé API ne lui est transmise et renvoie `result`."""
    out = json.dumps({"type": "result", "is_error": is_error, "result": result})
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "sys.stdin.read()\n"
        "assert 'ANTHROPIC_API_KEY' not in os.environ\n"
        f"print({out!r})\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-ne-doit-pas-passer")


@pytest.mark.skipif(os.name == "nt", reason="faux exécutable POSIX")
def test_claude_code_translates_with_account(tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, 'Voici : {"translation": "Hallo zusammen", "estimated_syllables": 4}')
    assert claude_code_path() == str(tmp_path / "claude")
    req = TranslationRequest(text="Bonjour à tous", source_lang="fr", target_locale="de-DE", target_seconds=1.5, max_units=6)
    assert ClaudeCodeTranslator().translate(req).text == "Hallo zusammen"


@pytest.mark.skipif(os.name == "nt", reason="faux exécutable POSIX")
def test_claude_code_not_logged_in_is_explained(tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, "Invalid API key · Please run /login", is_error=True)
    with pytest.raises(TranslationError, match="Se connecter à mon compte Claude"):
        run_claude_code("Reply OK")


def test_claude_code_engine_selected(app_env, monkeypatch):
    monkeypatch.setenv("DOUBLR_TRANSLATOR", "claude-code")
    from app import config
    config.reload_settings()
    from app.pipeline.translate import make_translator
    assert isinstance(make_translator(), ClaudeCodeTranslator)
