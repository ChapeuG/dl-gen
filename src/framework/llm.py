"""Fábrica de modelos de chat (LangChain).

O modelo é escolhido por string "provedor:modelo", ex:
    litellm:<modelo>            (proxy LiteLLM pela lib `openai`; chave lida do settings.json do Claude Code, ver abaixo)
    openai:gpt-4o-mini          (requer langchain-openai + OPENAI_API_KEY)
    anthropic:claude-sonnet-5-5 (requer langchain-anthropic + ANTHROPIC_API_KEY)
    azure_openai:<deployment>   (requer langchain-openai + variáveis AZURE_OPENAI_*)
    bedrock:<model-id>          (requer langchain-aws + credenciais AWS)

LiteLLM: URL e chave vêm de C:\\Users\\<matricula>\\.claude\\settings.json (Path.home()), no bloco "env"
(LITELLM_BASE_URL/LITELLM_API_KEY ou ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY) ou no
"apiKeyHelper". Variáveis de ambiente com os mesmos nomes prevalecem. $DL_CLAUDE_SETTINGS troca o arquivo.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

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


# Provedor → (pacote do LangChain, variável com a chave). Vazio = credencial que não dá para conferir aqui.
_PROVIDERS = {
    "openai": ("langchain_openai", "OPENAI_API_KEY"),
    "anthropic": ("langchain_anthropic", "ANTHROPIC_API_KEY"),
    "azure_openai": ("langchain_openai", "AZURE_OPENAI_API_KEY"),
    "bedrock": ("langchain_aws", ""),
}


def check_model(model: str) -> tuple[str, str]:
    """Confere se o modelo tem o que precisa (pacote, chave), sem chamar o LLM.

    Devolve (nível, mensagem): off (sem LLM), ok, warning (não deu para conferir) ou error (vai cair na heurística).
    A mensagem nunca traz a chave.
    """
    model = (model or "").strip()
    if not model:
        return "off", "Sem LLM: os nomes vêm do glossário (heurística)."
    if model.startswith(LITELLM_PREFIX):
        if importlib.util.find_spec("openai") is None:
            return "error", "Falta o pacote openai (pip install openai) para usar o LiteLLM. Usando o glossário."
        try:
            cfg = load_litellm_config()
        except RuntimeError as e:
            return "error", f"{e}. Usando o glossário."
        if cfg is None:
            return "error", f"Chave do LiteLLM não encontrada em {claude_settings_path()}. Usando o glossário."
        if not model[len(LITELLM_PREFIX):] and not cfg.model:
            return "error", "Informe o modelo: litellm:<modelo>."
        host = urlparse(cfg.base_url).netloc or cfg.base_url
        return "ok", f"LiteLLM configurado em {host} (chave do {Path(cfg.source).name})."
    provider = model.split(":", 1)[0] if ":" in model else ""
    if provider not in _PROVIDERS:
        return "warning", "Formato esperado: provedor:modelo (litellm, openai, anthropic, azure_openai ou bedrock)."
    package, key = _PROVIDERS[provider]
    if importlib.util.find_spec(package) is None:
        return "error", f"Falta o pacote {package} para usar {provider}. Usando o glossário."
    if not key:
        return "warning", f"{provider}: credenciais não conferidas aqui; uma falha cai no glossário."
    if not os.getenv(key):
        return "error", f"Variável {key} não definida. Usando o glossário."
    return "ok", f"{provider} configurado (chave em {key})."


LITELLM_TIMEOUT_S = 120

_ROLES = {"system": "system", "human": "user", "ai": "assistant"}


def get_openai_client(cfg: LiteLLMConfig | None = None):
    """Cliente da lib oficial da OpenAI apontando para o proxy LiteLLM (API compatível com OpenAI)."""
    from openai import OpenAI

    cfg = cfg or load_litellm_config()
    if cfg is None:
        raise RuntimeError(f"Chave do LiteLLM não encontrada em {claude_settings_path()} "
                           f"(env: {'/'.join(_BASE_URL_KEYS)} e {'/'.join(_API_KEY_KEYS)}, ou apiKeyHelper)")
    return OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=LITELLM_TIMEOUT_S, max_retries=2)


def _openai_messages(prompt) -> list[dict]:
    """Prompt do LangChain (ChatPromptValue/mensagens) ou texto → mensagens no formato da OpenAI."""
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    messages = prompt.to_messages() if hasattr(prompt, "to_messages") else prompt
    return [m if isinstance(m, dict) else {"role": _ROLES.get(m.type, "user"), "content": m.content} for m in messages]


class LiteLLMChat:
    """Modelo do LiteLLM chamado pela lib `openai` (client.chat.completions.create).

    Mesma interface que o agente usa do LangChain: `invoke(prompt)` devolve o texto e
    `with_structured_output(Modelo)` devolve um runnable que preenche o modelo Pydantic por tool calling
    (aceito por todos os modelos atrás do proxy).
    """

    def __init__(self, model: str, client, temperature: float = 0):
        self.model_name = model
        self.client = client
        self.temperature = temperature

    def _create(self, prompt, **kwargs):
        return self.client.chat.completions.create(model=self.model_name, messages=_openai_messages(prompt),
                                                   temperature=self.temperature, **kwargs)

    def invoke(self, prompt) -> str:
        return self._create(prompt).choices[0].message.content or ""

    def with_structured_output(self, schema, **_kwargs):
        from langchain_core.runnables import RunnableLambda

        name = schema.__name__
        tool = {"type": "function", "function": {"name": name, "description": (schema.__doc__ or name).strip(),
                                                 "parameters": schema.model_json_schema()}}

        def call(prompt):
            message = self._create(prompt, tools=[tool],
                                   tool_choice={"type": "function", "function": {"name": name}}).choices[0].message
            if message.tool_calls:
                return schema.model_validate_json(message.tool_calls[0].function.arguments)
            if message.content:  # modelo que respondeu em JSON no texto em vez de chamar a ferramenta
                return schema.model_validate_json(message.content.strip().removeprefix("```json").strip("`\n "))
            raise RuntimeError(f"O LLM não devolveu {name} (sem tool call nem conteúdo)")

        return RunnableLambda(call)


def _litellm_chat_model(model_name: str) -> LiteLLMChat:
    cfg = load_litellm_config()
    client = get_openai_client(cfg)
    name = model_name or cfg.model
    if not name:
        raise RuntimeError("Informe o modelo: --llm-model litellm:<modelo> (ou ANTHROPIC_MODEL no settings.json)")
    return LiteLLMChat(name, client)


def ping(model: str) -> str:
    """Chamada real e curta ao LLM, para conferir URL, chave e modelo. Devolve a resposta do modelo."""
    if not model:
        raise RuntimeError("Sem modelo: informe --llm-model (ex: litellm:<modelo>) ou ANTHROPIC_MODEL no settings.json")
    reply = get_chat_model(model).invoke("Responda apenas com a palavra: ok")
    return (reply if isinstance(reply, str) else getattr(reply, "content", str(reply))).strip()


def get_chat_model(model: str):
    """Instancia o modelo de chat (temperatura 0 = determinístico)."""
    if model.startswith(LITELLM_PREFIX):
        return _litellm_chat_model(model[len(LITELLM_PREFIX):])

    from langchain.chat_models import init_chat_model

    return init_chat_model(model, temperature=0)
