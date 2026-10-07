"""LiteLLM: chave lida do settings.json do Claude Code (C:\\Users\\<matricula>\\.claude\\settings.json)."""

from __future__ import annotations

import json
import sys

import pytest
from pydantic import BaseModel

from framework.llm import CLAUDE_SETTINGS_ENV, check_model, get_chat_model, load_litellm_config, resolve_model_name


def _settings(tmp_path, monkeypatch, data: dict):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(CLAUDE_SETTINGS_ENV, str(path))
    return path


def test_reads_env_block(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch, {"env": {"ANTHROPIC_BASE_URL": "https://litellm.example/", "ANTHROPIC_AUTH_TOKEN": "sk-1",
                                              "ANTHROPIC_MODEL": "claude-sonnet-5-5"}})
    cfg = load_litellm_config()
    assert (cfg.base_url, cfg.api_key, cfg.model) == ("https://litellm.example", "sk-1", "claude-sonnet-5-5")
    assert "sk-1" not in repr(cfg)


def test_litellm_names_and_environment_override(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch, {"env": {"LITELLM_BASE_URL": "https://a", "LITELLM_API_KEY": "sk-a"}})
    monkeypatch.setenv("LITELLM_API_KEY", "sk-env")
    cfg = load_litellm_config()
    assert (cfg.base_url, cfg.api_key, cfg.model) == ("https://a", "sk-env", "")


def test_api_key_helper(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch, {"env": {"ANTHROPIC_BASE_URL": "https://a"},
                                      "apiKeyHelper": f'"{sys.executable}" -c "print(\'sk-helper\')"'})
    assert load_litellm_config().api_key == "sk-helper"


def test_missing_settings_or_key(tmp_path, monkeypatch):
    assert load_litellm_config() is None  # conftest aponta para arquivo inexistente
    _settings(tmp_path, monkeypatch, {"env": {"ANTHROPIC_BASE_URL": "https://a"}})
    assert load_litellm_config() is None
    with pytest.raises(RuntimeError, match="Chave do LiteLLM não encontrada"):
        get_chat_model("litellm:claude")


def test_resolve_model_name(tmp_path, monkeypatch):
    assert resolve_model_name("") == ""  # sem settings: heurística
    _settings(tmp_path, monkeypatch, {"env": {"ANTHROPIC_BASE_URL": "https://a", "ANTHROPIC_API_KEY": "k",
                                              "ANTHROPIC_MODEL": "claude-x"}})
    assert resolve_model_name("") == "litellm:claude-x"
    assert resolve_model_name("openai:gpt") == "openai:gpt"
    monkeypatch.setenv("DL_LLM_MODEL", "litellm:outro")
    assert resolve_model_name("") == "litellm:outro"


class _Out(BaseModel):
    nome: str


def test_chat_model_points_to_proxy(tmp_path, monkeypatch):
    _settings(tmp_path, monkeypatch, {"env": {"ANTHROPIC_BASE_URL": "https://litellm.example", "ANTHROPIC_AUTH_TOKEN": "sk-1",
                                              "ANTHROPIC_MODEL": "claude-default"}})
    model = get_chat_model("litellm:")
    assert model.model_name == "claude-default"
    assert model.openai_api_base == "https://litellm.example"
    assert model.openai_api_key.get_secret_value() == "sk-1"
    assert get_chat_model("litellm:claude-sonnet-5-5").model_name == "claude-sonnet-5-5"
    model.with_structured_output(_Out)  # tool calling, sem chamada de rede


def test_check_model(tmp_path, monkeypatch):
    assert check_model("")[0] == "off"
    assert check_model("litellm:claude")[0] == "error"  # sem settings.json
    _settings(tmp_path, monkeypatch, {"env": {"ANTHROPIC_BASE_URL": "https://litellm.example/v1", "ANTHROPIC_AUTH_TOKEN": "sk-1"}})
    level, message = check_model("litellm:claude")
    assert level == "ok" and "litellm.example" in message and "sk-1" not in message
    assert check_model("litellm:")[0] == "error"  # sem modelo no campo nem no settings
    assert check_model("gpt-4o")[0] == "warning"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert check_model("openai:gpt-4o-mini") == ("error", "Variável OPENAI_API_KEY não definida. Usando o glossário.")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-2")
    assert check_model("openai:gpt-4o-mini")[0] == "ok"
