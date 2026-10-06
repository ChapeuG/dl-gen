"""Fábrica de modelos de chat (LangChain).

O modelo é escolhido por string "provedor:modelo", ex:
    litellm:<modelo>            (proxy LiteLLM; chave lida do settings.json do Claude Code, ver abaixo)
    openai:gpt-4o-mini          (requer langchain-openai + OPENAI_API_KEY)
    anthropic:claude-sonnet-5-5 (requer langchain-anthropic + ANTHROPIC_API_KEY)
    azure_openai:<deployment>   (requer langchain-openai + variáveis AZURE_OPENAI_*)
    bedrock:<model-id>          (requer langchain-aws + credenciais AWS)

LiteLLM: URL e chave vêm de C:\\Users\\<matricula>\\.claude\\settings.json (Path.home()), no bloco "env"
(LITELLM_BASE_URL/LITELLM_API_KEY ou ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY) ou no
"apiKeyHelper". Variáveis de ambiente com os mesmos nomes prevalecem. $DL_CLAUDE_SETTINGS troca o arquivo.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL_ENV = "DL_LLM_MODEL"
CLAUDE_SETTINGS_ENV = "DL_CLAUDE_SETTINGS"
LITELLM_PREFIX = "litellm:"

_BASE_URL_KEYS = ("LITELLM_BASE_URL", "LITELLM_API_BASE", "ANTHROPIC_BASE_URL")
_API_KEY_KEYS = ("LITELLM_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
_MODEL_KEYS = ("LITELLM_MODEL", "ANTHROPIC_MODEL")


@dataclass(frozen=True)
class LiteLLMConfig:
    base_url: str
    api_key: str
    model: str  # modelo default do settings (vazio = informe em --llm-model litellm:<modelo>)
    source: str

    def __repr__(self) -> str:  # nunca expõe a chave em log/traceback
        return f"LiteLLMConfig(base_url={self.base_url!r}, model={self.model!r}, source={self.source!r})"


def claude_settings_path() -> Path:
    return Path(os.getenv(CLAUDE_SETTINGS_ENV) or Path.home() / ".claude" / "settings.json")


def _read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Não consegui ler {path}: {e}") from e
    return data if isinstance(data, dict) else {}


def _api_key_helper(command: str) -> str:
    """apiKeyHelper do Claude Code: comando que imprime a chave."""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("apiKeyHelper do settings.json não respondeu em 30s") from e
    if result.returncode != 0:
        raise RuntimeError(f"apiKeyHelper do settings.json falhou (código {result.returncode})")
    return result.stdout.strip()


def load_litellm_config(path: Path | None = None) -> LiteLLMConfig | None:
    """URL, chave e modelo do LiteLLM (ambiente > settings.json). None se não houver URL e chave."""
    path = path or claude_settings_path()
    settings = _read_settings(path)
    env = settings.get("env") if isinstance(settings.get("env"), dict) else {}

    def lookup(names: tuple[str, ...]) -> str:
        for name in names:
            value = os.environ.get(name) or env.get(name)
            if value:
                return str(value).strip()
        return ""

    base_url = lookup(_BASE_URL_KEYS)
    api_key = lookup(_API_KEY_KEYS)
    if not api_key and settings.get("apiKeyHelper"):
        api_key = _api_key_helper(str(settings["apiKeyHelper"]))
    if not base_url or not api_key:
        return None
    return LiteLLMConfig(base_url=base_url.rstrip("/"), api_key=api_key, model=lookup(_MODEL_KEYS), source=str(path))


def resolve_model_name(cli_value: str | None = None) -> str:
    """--llm-model > $DL_LLM_MODEL > LiteLLM do settings.json (se tiver modelo) > vazio (heurística)."""
    if cli_value or os.getenv(DEFAULT_MODEL_ENV):
        return cli_value or os.getenv(DEFAULT_MODEL_ENV, "")
    try:
        cfg = load_litellm_config()
    except RuntimeError:
        return ""
    return f"{LITELLM_PREFIX}{cfg.model}" if cfg and cfg.model else ""


def _litellm_chat_model(model_name: str):
    from langchain_openai import ChatOpenAI

    cfg = load_litellm_config()
    if cfg is None:
        raise RuntimeError(f"Chave do LiteLLM não encontrada em {claude_settings_path()} "
                           f"(env: {'/'.join(_BASE_URL_KEYS)} e {'/'.join(_API_KEY_KEYS)}, ou apiKeyHelper)")
    name = model_name or cfg.model
    if not name:
        raise RuntimeError("Informe o modelo: --llm-model litellm:<modelo> (ou ANTHROPIC_MODEL no settings.json)")

    class LiteLLMChat(ChatOpenAI):
        """Proxy LiteLLM (API compatível com OpenAI). Saída estruturada por tool calling, aceita por todos os modelos."""

        def with_structured_output(self, schema, **kwargs):
            kwargs.setdefault("method", "function_calling")
            return super().with_structured_output(schema, **kwargs)

    return LiteLLMChat(model=name, base_url=cfg.base_url, api_key=cfg.api_key, temperature=0)


def get_chat_model(model: str):
    """Instancia o modelo de chat (temperatura 0 = determinístico)."""
    if model.startswith(LITELLM_PREFIX):
        return _litellm_chat_model(model[len(LITELLM_PREFIX):])

    from langchain.chat_models import init_chat_model

    return init_chat_model(model, temperature=0)
