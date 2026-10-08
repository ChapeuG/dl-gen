"""LiteLLM: chave lida do settings.json do Claude Code (C:\\Users\\<matricula>\\.claude\\settings.json)."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from framework.llm import (CLAUDE_SETTINGS_ENV, LiteLLMChat, check_model, get_chat_model, load_litellm_config, ping,
                           resolve_model_name)


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


def test_chat_model_uses_openai_client_on_proxy(tmp_path, monkeypatch):
    from openai import OpenAI

    _settings(tmp_path, monkeypatch, {"env": {"ANTHROPIC_BASE_URL": "https://litellm.example", "ANTHROPIC_AUTH_TOKEN": "sk-1",
                                              "ANTHROPIC_MODEL": "claude-default"}})
    model = get_chat_model("litellm:")
    assert isinstance(model.client, OpenAI)
    assert model.model_name == "claude-default"
    assert str(model.client.base_url).rstrip("/") == "https://litellm.example"
    assert model.client.api_key == "sk-1"
    assert get_chat_model("litellm:claude-sonnet-5-5").model_name == "claude-sonnet-5-5"


class _FakeCompletions:
    """Imita client.chat.completions da lib openai e guarda o que foi enviado."""

    def __init__(self, message):
        self.message, self.calls = message, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=self.message)])


def _fake_model(message):
    completions = _FakeCompletions(message)
    return LiteLLMChat("claude-x", SimpleNamespace(chat=SimpleNamespace(completions=completions))), completions


def test_structured_output_by_tool_call():
    from langchain_core.prompts import ChatPromptTemplate

    tool_call = SimpleNamespace(function=SimpleNamespace(arguments='{"nome": "nm_cliente"}'))
    model, completions = _fake_model(SimpleNamespace(tool_calls=[tool_call], content=None))
    prompt = ChatPromptTemplate.from_messages([("system", "regras {x}"), ("human", "campo {y}")])
    result = (prompt | model.with_structured_output(_Out)).invoke({"x": "A", "y": "name"})

    assert result == _Out(nome="nm_cliente")
    sent = completions.calls[0]
    assert sent["model"] == "claude-x" and sent["temperature"] == 0
    assert sent["messages"] == [{"role": "system", "content": "regras A"}, {"role": "user", "content": "campo name"}]
    assert sent["tool_choice"] == {"type": "function", "function": {"name": "_Out"}}
    assert sent["tools"][0]["function"]["parameters"]["properties"]["nome"]["type"] == "string"


def test_structured_output_from_json_text_and_ping(tmp_path, monkeypatch):
    model, _ = _fake_model(SimpleNamespace(tool_calls=None, content='```json\n{"nome": "nm_x"}\n```'))
    assert model.with_structured_output(_Out).invoke("oi") == _Out(nome="nm_x")

    model, completions = _fake_model(SimpleNamespace(tool_calls=None, content=" ok "))
    monkeypatch.setattr("framework.llm.get_chat_model", lambda name: model)
    assert ping("litellm:claude-x") == "ok"
    assert completions.calls[0]["messages"][0]["role"] == "user"
    with pytest.raises(RuntimeError, match="Sem modelo"):
        ping("")


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
