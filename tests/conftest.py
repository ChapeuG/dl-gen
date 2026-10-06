"""Isola os testes do LLM configurado na máquina (settings.json do Claude Code / variáveis do LiteLLM)."""

from __future__ import annotations

import pytest

from framework.llm import _API_KEY_KEYS, _BASE_URL_KEYS, _MODEL_KEYS, CLAUDE_SETTINGS_ENV, DEFAULT_MODEL_ENV


@pytest.fixture(autouse=True)
def _no_machine_llm(monkeypatch, tmp_path):
    monkeypatch.setenv(CLAUDE_SETTINGS_ENV, str(tmp_path / "sem-settings.json"))
    for name in (DEFAULT_MODEL_ENV, *_BASE_URL_KEYS, *_API_KEY_KEYS, *_MODEL_KEYS):
        monkeypatch.delenv(name, raising=False)
