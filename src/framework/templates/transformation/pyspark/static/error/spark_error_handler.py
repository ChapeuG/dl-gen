"""Classificacao de erros do job Spark em categorias acionaveis.

Percorre a cadeia causal do erro — excecoes Python (``__cause__``/``__context__``)
e, quando o erro vem da JVM (Py4JJavaError), a cadeia ``getCause()`` da excecao
Java — e aplica as regras na ordem abaixo. A primeira regra que casar define a
categoria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# ── Categorias de erro ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ErrorCategory:
    name: str
    retryable: bool
    programming_error: bool
    summary: str
    cause: BaseException | None = None
    detail: str = ""

    @property
    def description(self) -> str:
        return f"{self.summary} Detail: {self.detail or (str(self.cause) if self.cause else '')}"


_CATEGORIES = {
    #  nome                       retryable  programming  resumo
    "ConnectivityError":       (True,  False, "Connectivity/network failure — retryable."),
    "ResourceExhaustionError": (True,  False, "Resource exhaustion (OOM / disk / shuffle) — retryable with resource adjustment."),
    "DataSchemaError":         (False, True,  "Data/schema error — programming fix required."),
    "AuthorizationError":      (False, False, "Authorization/authentication failure — credentials or ACL fix required."),
    "BroadcastTimeoutError":   (True,  False, "Broadcast join timeout — consider increasing spark.sql.broadcastTimeout or disabling broadcast."),
    "ConfigurationError":      (False, True,  "Job configuration error — fix configuration before retrying."),
    "UnknownError":            (False, False, "Unknown/unclassified error — manual investigation required."),
}

_SUGGESTED_ACTIONS = {
    "ConnectivityError": "Retry with exponential backoff. Verify network/DNS, check endpoint availability and firewall rules.",
    "ResourceExhaustionError": "Retry after increasing executor memory/cores or reducing partition size. Review broadcast join thresholds.",
    "DataSchemaError": "Do NOT retry automatically. Fix schema definition, column names, or data casting logic in the code.",
    "AuthorizationError": "Do NOT retry automatically. Renew Kerberos ticket or fix IAM/ACL permissions, then redeploy.",
    "BroadcastTimeoutError": "Retry after increasing spark.sql.broadcastTimeout or disabling broadcast with spark.sql.autoBroadcastJoinThreshold=-1.",
    "ConfigurationError": "Do NOT retry automatically. Fix job configuration, dependencies, or invalid parameters.",
    "UnknownError": "Manual investigation required. Check driver/executor logs for full stack trace.",
}


def _category(name: str, cause: BaseException | None, detail: str = "") -> ErrorCategory:
    retryable, programming, summary = _CATEGORIES[name]
    return ErrorCategory(name, retryable, programming, summary, cause, detail)


# ── Resultado padronizado do handler ───────────────────────────────────


@dataclass(frozen=True)
class SparkErrorResult:
    category: ErrorCategory
    original_error: BaseException
    retryable: bool
    programming_error: bool
    suggested_action: str


# ── Cadeia causal (Python + JVM) ───────────────────────────────────────


@dataclass
class _Link:
    """Um elo da cadeia causal: nomes das classes (com as superclasses) e mensagem."""
    classes: set[str]
    message: str
    sql_state: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def is_a(self, *names: str) -> bool:
        return any(n in self.classes for n in names)

    def contains(self, fragment: str) -> bool:
        return fragment.lower() in self.message.lower()


def _java_links(jexc: Any) -> list[_Link]:
    links, seen = [], set()
    while jexc is not None and len(links) < 50:
        key = jexc.hashCode()
        if key in seen:
            break
        seen.add(key)
        classes, cls = set(), jexc.getClass()
        while cls is not None:
            classes.add(cls.getSimpleName())
            cls = cls.getSuperclass()
        sql_state = ""
        if "SQLException" in classes:
            sql_state = jexc.getSQLState() or ""
        links.append(_Link(classes, jexc.getMessage() or "", sql_state))
        jexc = jexc.getCause()
    return links


def _causal_chain(error: BaseException) -> list[_Link]:
    links, seen = [], set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        links.append(_Link({c.__name__ for c in type(current).__mro__}, str(current)))
        java = getattr(current, "java_exception", None)  # py4j.protocol.Py4JJavaError
        if java is not None:
            try:
                links.extend(_java_links(java))
            except Exception:  # gateway indisponivel: fica so com a parte Python
                pass
        current = current.__cause__ or current.__context__
    return links


# ── Regras (na ordem de prioridade) ────────────────────────────────────


def _is_auth(link: _Link) -> bool:
    msg = link.message.lower()
    cls = " ".join(link.classes).lower()
    return any(s in msg for s in ("kerberos", "authentication failed", "403", "access denied", "permission denied")) \
        or "accesscontrolexception" in cls or "accessdenied" in cls


def _is_connectivity_io(link: _Link) -> bool:
    msg = link.message.lower()
    return any(s in msg for s in ("connection", "network", "unreachable", "s3", "hdfs", "timeout"))


_RULES: list[tuple[Callable[[_Link], bool], str, Callable[[_Link], str]]] = [
    (lambda e: e.is_a("SparkException") and e.contains("broadcast") and (e.contains("timeout") or e.contains("timed out")),
     "BroadcastTimeoutError", lambda e: "spark.sql.broadcastTimeout exceeded"),
    (lambda e: e.is_a("SparkException") and (e.contains("FetchFailed") or (e.contains("shuffle") and e.contains("failed"))),
     "ResourceExhaustionError", lambda e: "Shuffle FetchFailedException — possible executor loss or disk pressure"),
    (lambda e: e.is_a("OutOfMemoryError", "MemoryError"),
     "ResourceExhaustionError", lambda e: "OutOfMemoryError"),
    (lambda e: e.is_a("SparkException") and e.contains("GC overhead limit exceeded"),
     "ResourceExhaustionError", lambda e: "GC overhead limit — increase executor memory"),
    (lambda e: e.is_a("IOException", "OSError") and e.contains("No space left on device"),
     "ResourceExhaustionError", lambda e: "Disk full on executor/driver node"),
    (_is_auth, "AuthorizationError", lambda e: "ACL or Kerberos authentication failure"),
    (lambda e: e.is_a("SecurityException", "PermissionError"),
     "AuthorizationError", lambda e: "SecurityException — check IAM roles or file permissions"),
    (lambda e: e.is_a("AnalysisException"),
     "DataSchemaError", lambda e: f"Spark AnalysisException: {e.message}"),
    (lambda e: e.is_a("NoSuchTableException"),
     "DataSchemaError", lambda e: f"Table not found: {e.message}"),
    (lambda e: e.is_a("ConnectException", "ConnectionRefusedError"),
     "ConnectivityError", lambda e: f"TCP connection refused: {e.message}"),
    (lambda e: e.is_a("UnknownHostException", "gaierror"),
     "ConnectivityError", lambda e: f"DNS resolution failure: {e.message}"),
    (lambda e: e.is_a("SocketTimeoutException", "TimeoutError"),
     "ConnectivityError", lambda e: f"Socket timeout: {e.message}"),
    (lambda e: e.is_a("IOException", "ConnectionError") and _is_connectivity_io(e),
     "ConnectivityError", lambda e: e.message),
    (lambda e: e.is_a("SQLException") and e.sql_state.startswith("08"),
     "ConnectivityError", lambda e: f"JDBC connectivity error (SQLState: {e.sql_state}): {e.message}"),
    (lambda e: e.is_a("ClassNotFoundException", "ModuleNotFoundError"),
     "ConfigurationError", lambda e: f"Class/module not found — check --jars, --packages or --py-files: {e.message}"),
    (lambda e: e.is_a("NoClassDefFoundError", "ImportError"),
     "ConfigurationError", lambda e: f"Dependency missing: {e.message}"),
    (lambda e: e.is_a("IllegalArgumentException", "ValueError", "KeyError"),
     "ConfigurationError", lambda e: f"Illegal argument — check job parameters: {e.message}"),
]


def _classify_internal(error: BaseException) -> ErrorCategory:
    for link in _causal_chain(error):
        for matches, name, detail in _RULES:
            if matches(link):
                return _category(name, error, detail(link))
    return _category("UnknownError", error)


# ── API ────────────────────────────────────────────────────────────────


def classify(error: BaseException) -> SparkErrorResult:
    category = _classify_internal(error)
    return SparkErrorResult(
        category=category,
        original_error=error,
        retryable=category.retryable,
        programming_error=category.programming_error,
        suggested_action=_SUGGESTED_ACTIONS[category.name],
    )


def run(block: Callable[[], T]) -> tuple[T | None, SparkErrorResult | None]:
    """Executa o bloco e devolve ``(valor, None)`` ou ``(None, erro_classificado)``."""
    try:
        return block(), None
    except Exception as e:  # noqa: BLE001 — classifica qualquer falha do job
        return None, classify(e)
