"""Lógica da interface (sem Streamlit): formulário ↔ data contract, nomenclatura, validação e geração.

Fluxo da interface:
    1. Contrato   — formulário + colunas (DDL, contrato existente ou digitadas) → data contract ODCS
    2. Campos     — nomenclatura proposta (heurística/LLM), editável → vira stagingName no contrato
    3. Validação  — contrato, campos obrigatórios, padrão de nomenclatura e simulação da geração
    4. Geração    — grava contrato, ingestion.yml e projeto de transformação
"""

from __future__ import annotations

import contextlib
import io
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from framework.cli import _initial_state
from framework.ingestion_config import placeholders
from framework.parsers.contract_parser import custom_props, load_contract
from framework.parsers.ddl_parser import parse_ddl
from framework.standards.nomenclatura import validate_naming
from framework.standards.sources import SOURCES, get_source

ODCS_VERSION = "v3.2.0"
SOURCE_TYPES = sorted(SOURCES)
LOGICAL_TYPES = ["string", "integer", "number", "boolean", "date", "timestamp", "time", "array", "object"]
ENVIRONMENTS = ["dev", "hml", "prd"]

_SPARK_TO_LOGICAL = {
    "StringType": "string", "BooleanType": "boolean", "IntegerType": "integer", "LongType": "integer",
    "ShortType": "integer", "ByteType": "integer", "DoubleType": "number", "FloatType": "number",
    "DateType": "date", "TimestampType": "timestamp",
}

COLUMN_KEYS = ["name", "physicalType", "logicalType", "primaryKey", "required", "partitioned", "encrypt", "description"]
SERVER_KEYS = ["environment", "host", "port", "database", "secretId"]


def empty_form() -> dict:
    return {
        "id": str(uuid.uuid4()), "version": "1.0.0", "dataset": "", "domain": "", "table": "", "physicalName": "",
        "description": "", "owner": "", "sourceType": "postgres", "schema": "",
        "loadMode": "incremental", "incrementalColumns": [], "fetchSize": 150000, "numQueriesParallel": 1,
        "rawPath": "", "rawDatabase": "", "rawPartitionColumn": "", "cryptographySecretArn": "",
        "qualityUniqueKey": True, "qualityNotEmpty": True,
    }


def empty_servers() -> list[dict]:
    return [{"environment": "prd", "host": "", "port": None, "database": "", "secretId": ""}]


def _logical(spark_type: str) -> str:
    if spark_type.startswith("DecimalType"):
        return "number"
    if spark_type.startswith("ArrayType"):
        return "array"
    return _SPARK_TO_LOGICAL.get(spark_type, "string")


# ── Entrada das colunas ────────────────────────────────────────────────

def columns_from_ddl(ddl: str, source_type: str = "postgres") -> tuple[dict, list[dict]]:
    """DDL (CREATE TABLE) → (campos do formulário, linhas de colunas)."""
    schema = parse_ddl(ddl, type_map=dict(get_source(source_type).type_overrides))
    rows = [{
        "name": f["raw_field"], "physicalType": f["raw_type"], "logicalType": _logical(f["data_type"]),
        "primaryKey": f["is_pk"], "required": not f["nullable"], "partitioned": False, "encrypt": False,
        "description": f["comment"],
    } for f in schema["fields"]]
    # Sugestão de coluna incremental: o primeiro candidato de data do DDL
    for r in rows:
        if r["name"] in schema["partition_candidates"]:
            r["partitioned"] = True
            break
    form = {"table": schema["table_name"], "physicalName": schema["source_table"],
            "description": schema["table_comment"]}
    return form, rows


def form_from_contract(text: str, table: str = "") -> tuple[dict, list[dict], list[dict]]:
    """Contrato ODCS existente → (formulário, servidores, colunas)."""
    contract = load_contract(text)
    tables = contract["schema"]
    t = next((x for x in tables if x["name"] == table), tables[0]) if table else tables[0]
    tp, cp = custom_props(t), custom_props(contract)
    servers = contract.get("servers") or []

    form = {**empty_form(),
            "id": str(contract.get("id") or uuid.uuid4()), "version": str(contract.get("version", "1.0.0")),
            "dataset": contract.get("dataProduct", ""), "domain": contract.get("domain", ""),
            "table": t["name"], "physicalName": t.get("physicalName", ""),
            "description": t.get("description") or (contract.get("description") or {}).get("purpose", ""),
            "owner": next((m.get("username", "") for m in (contract.get("team") or {}).get("members", [])), ""),
            "sourceType": str(servers[0].get("type", "postgres")) if servers else "postgres",
            "schema": next((s.get("schema", "") for s in servers if s.get("schema")), ""),
            "loadMode": tp.get("loadMode", "incremental"), "incrementalColumns": list(tp.get("incrementalColumns") or []),
            "fetchSize": int(tp.get("fetchSize") or 150000), "numQueriesParallel": int(tp.get("numQueriesParallel") or 1),
            "rawPath": tp.get("rawPath", ""), "rawDatabase": tp.get("rawDatabase", ""),
            "rawPartitionColumn": tp.get("rawPartitionColumn", ""),
            "cryptographySecretArn": tp.get("cryptographySecretArn", ""),
            "qualityUniqueKey": any(q.get("metric") == "duplicateValues" for q in t.get("quality") or []),
            "qualityNotEmpty": any(q.get("metric") == "rowCount" for q in t.get("quality") or []),
            "githubOrg": cp.get("githubOrg", "")}
    server_rows = [{"environment": s.get("environment", ""), "host": s.get("host", ""), "port": s.get("port"),
                    "database": s.get("database") or s.get("serviceName", ""),
                    "secretId": custom_props(s).get("secretId", "")} for s in servers] or empty_servers()
    columns = [{
        "name": p.get("physicalName") or p["name"], "physicalType": p.get("physicalType", ""),
        "logicalType": p.get("logicalType", "string"), "primaryKey": bool(p.get("primaryKey")),
        "required": bool(p.get("required")), "partitioned": bool(p.get("partitioned")),
        "encrypt": str(custom_props(p).get("encrypt", "")).lower() == "true" or custom_props(p).get("encrypt") is True,
        "description": p.get("description", ""), "stagingName": custom_props(p).get("stagingName", ""),
    } for p in t["properties"]]
    return form, server_rows, columns


# ── Formulário → data contract ─────────────────────────────────────────

def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _props(items: dict) -> list[dict]:
    return [{"property": k, "value": v} for k, v in items.items() if v not in (None, "", [], False)]


def _port(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_DEFAULT_SCHEMA = {"postgres": "public", "sqlserver": "dbo"}


def _server_schema(form: dict, source_type: str) -> str:
    """schema do servidor (o ODCS exige em postgres e sqlserver): informado > prefixo da tabela > padrão do banco."""
    if source_type not in _DEFAULT_SCHEMA:
        return ""
    physical = str(form.get("physicalName") or "")
    return (str(form.get("schema") or "").strip() or (physical.split(".")[0] if "." in physical else "")
            or _DEFAULT_SCHEMA[source_type])


def build_contract(form: dict, servers: list[dict], columns: list[dict], naming: dict[str, dict] | None = None) -> dict:
    """Monta o data contract ODCS. naming: coluna → {staging_field, comment} revisados na etapa 2."""
    naming = naming or {}
    dataset = str(form.get("dataset", "")).strip().lower()
    table = str(form.get("table", "")).strip()
    source_type = form.get("sourceType", "postgres")
    cols = [c for c in columns if str(c.get("name") or "").strip()]

    contract_servers = []
    for s in servers:
        env = str(s.get("environment") or "").strip()
        if not env:
            continue
        db_key = "serviceName" if source_type == "oracle" else "database"
        contract_servers.append(_clean({
            "server": f"{dataset or 'origem'}-{env}", "environment": env, "type": source_type,
            "host": str(s.get("host") or "").strip(), "port": _port(s.get("port")),
            db_key: str(s.get("database") or "").strip(),
            "schema": _server_schema(form, source_type),
            "customProperties": _props({"secretId": str(s.get("secretId") or "").strip()}),
        }))

    pk_pos = 0
    properties = []
    for c in cols:
        name = str(c["name"]).strip()
        review = naming.get(name, {})
        pk = bool(c.get("primaryKey"))
        if pk:
            pk_pos += 1
        properties.append(_clean({
            "name": name,
            "logicalType": c.get("logicalType") or "string",
            "physicalType": str(c.get("physicalType") or "").strip(),
            "primaryKey": pk or None, "primaryKeyPosition": pk_pos if pk else None,
            "required": bool(c.get("required")) or pk or None,
            "partitioned": bool(c.get("partitioned")) or None,
            "partitionKeyPosition": 1 if c.get("partitioned") else None,
            "description": (review.get("comment") or c.get("description") or "").strip(),
            "classification": "restricted" if c.get("encrypt") else None,
            "customProperties": _props({
                "encrypt": bool(c.get("encrypt")),
                "stagingName": (review.get("staging_field") or c.get("stagingName") or "").strip(),
            }),
        }))

    quality = []
    pk_cols = [str(c["name"]).strip() for c in cols if c.get("primaryKey")]
    if form.get("qualityUniqueKey") and pk_cols:
        quality.append({"metric": "duplicateValues", "mustBe": 0, "severity": "error",
                        "description": "Uma linha por chave", "arguments": {"properties": pk_cols}})
    if form.get("qualityNotEmpty"):
        quality.append({"metric": "rowCount", "mustBeGreaterThan": 0, "severity": "warning",
                        "description": "A carga não deve vir vazia"})

    encrypt = any(c.get("encrypt") for c in cols)
    table_props = _props({
        "loadMode": form.get("loadMode"),
        "incrementalColumns": [c for c in form.get("incrementalColumns") or [] if c],
        "fetchSize": int(form.get("fetchSize") or 150000) if int(form.get("fetchSize") or 150000) != 150000 else None,
        "numQueriesParallel": int(form.get("numQueriesParallel") or 1) if int(form.get("numQueriesParallel") or 1) > 1 else None,
        "rawPartitionColumn": str(form.get("rawPartitionColumn") or "").strip(),
        "rawPath": str(form.get("rawPath") or "").strip(),
        "rawDatabase": str(form.get("rawDatabase") or "").strip(),
        "cryptographySecretArn": str(form.get("cryptographySecretArn") or "").strip() if encrypt else "",
    })

    contract = _clean({
        "apiVersion": ODCS_VERSION, "kind": "DataContract", "id": form.get("id") or str(uuid.uuid4()),
        "name": f"{dataset}-{table}" if dataset and table else "", "version": form.get("version") or "1.0.0",
        "status": "draft", "domain": str(form.get("domain") or "").strip(), "dataProduct": dataset,
        "description": _clean({"purpose": str(form.get("description") or "").strip()}),
        "team": {"name": "dono-do-dado", "members": [{"username": form["owner"].strip(), "role": "owner"}]}
        if str(form.get("owner") or "").strip() else None,
        "servers": contract_servers,
        "schema": [_clean({
            "name": table, "physicalName": str(form.get("physicalName") or "").strip(), "physicalType": "table",
            "description": str(form.get("description") or "").strip(),
            "customProperties": table_props, "properties": properties, "quality": quality,
        })],
        "customProperties": _props({"githubOrg": str(form.get("githubOrg") or "").strip()}),
    })
    return contract


def dump_contract(contract: dict) -> str:
    return yaml.safe_dump(contract, sort_keys=False, allow_unicode=True, width=120)


# ── Etapa 2: nomenclatura ──────────────────────────────────────────────

def _state(contract_text: str, llm_model: str = "", naming_dir: str = "", dry_run: bool = True) -> dict:
    return _initial_state(None, None, None, None, llm_model or "", naming_dir, dry_run, contract_text=contract_text)


@dataclass
class NamingResult:
    rows: list[dict]
    source: str
    warnings: list[str] = field(default_factory=list)


def propose_naming(contract_text: str, llm_model: str = "") -> NamingResult:
    """Roda profiler + nomenclatura (sem gravar nada) e devolve as linhas para revisão."""
    from framework.agents.naming import naming_agent
    from framework.agents.profiler import profiler_agent

    state = _state(contract_text, llm_model)
    with contextlib.redirect_stdout(io.StringIO()):
        state.update(profiler_agent(state))
        state.update(naming_agent(state))
    rows = [{
        "raw_field": f["raw_field"], "data_type": f["data_type"], "staging_field": f["staging_field"],
        "comment": f["comment"], "primaryKey": f["is_pk"], "encrypt": bool(f.get("encrypt")),
    } for f in state["schema"]["fields"]]
    return NamingResult(rows, state.get("naming_source", ""), list(state.get("naming_warnings") or []))


def naming_map(rows: list[dict]) -> dict[str, dict]:
    return {r["raw_field"]: {"staging_field": str(r.get("staging_field") or "").strip().lower(),
                             "comment": str(r.get("comment") or "").strip()} for r in rows}


# ── Etapa 3: validação ─────────────────────────────────────────────────

@dataclass
class Check:
    level: str   # ok | warning | error
    title: str
    detail: str = ""


@dataclass
class ValidationResult:
    checks: list[Check]
    files: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(c.level == "error" for c in self.checks)


def _required_checks(contract: dict) -> list[Check]:
    checks: list[Check] = []
    table = (contract.get("schema") or [{}])[0]
    props = table.get("properties") or []
    tp = custom_props(table)

    def need(cond: bool, title: str, detail: str, level: str = "error"):
        checks.append(Check("ok" if cond else level, title, "" if cond else detail))

    need(bool(contract.get("dataProduct")), "Dataset informado", "Preencha o dataset na etapa 1.")
    need(bool(table.get("name")), "Tabela informada", "Preencha o nome da tabela.")
    need(bool(props), "Colunas informadas", "Adicione as colunas (importe a DDL ou digite).")
    need(any(p.get("primaryKey") for p in props), "Chave primária marcada",
         "Marque ao menos uma coluna como chave: ela é a chave do MERGE na transformação.")
    partitioned = [p["name"] for p in props if p.get("partitioned")]
    need(len(partitioned) <= 1, "No máximo uma coluna incremental", f"Marcadas: {', '.join(partitioned)}.")
    if tp.get("loadMode") == "incremental":
        need(len(partitioned) == 1, "Coluna incremental marcada",
             "Carga incremental precisa de uma coluna de data marcada como incremental (ou use carga full).")
    servers = contract.get("servers") or []
    need(bool(servers), "Servidor de origem", "Informe ao menos um ambiente (dev, hml ou prd).")
    for s in servers:
        need(bool(custom_props(s).get("secretId")), f"Secret do ambiente {s.get('environment')}",
             "Informe o ID/ARN da secret com usuário e senha.")
        need(bool(s.get("host")), f"Host do ambiente {s.get('environment')}",
             "Sem host no contrato: ele precisa estar na secret (host ou url).", level="warning")
    need(bool(tp.get("rawPartitionColumn")), "Coluna de partição da raw", "Informe a coluna de partição da raw.")
    need(bool(tp.get("rawPath")), "Destino na raw (rawPath)", "Informe o caminho S3 da raw (use {env} para o ambiente).")
    if any(str(custom_props(p).get("encrypt")).lower() == "true" for p in props):
        need(bool(tp.get("cryptographySecretArn")), "Chave de criptografia",
             "Há coluna criptografada: informe o ARN da secret com a chave AES.")
    return checks


def validate(contract: dict) -> ValidationResult:
    """Checklist da etapa 3 + simulação da geração (nada é gravado)."""
    from framework.agents.input_gen import input_gen_agent
    from framework.agents.naming import naming_agent
    from framework.agents.profiler import profiler_agent
    from framework.agents.transform_gen import transform_gen_agent

    text = dump_contract(contract)
    checks: list[Check] = []
    try:
        load_contract(text)
        checks.append(Check("ok", "Estrutura do data contract (ODCS)"))
    except ValueError as e:
        return ValidationResult([Check("error", "Estrutura do data contract (ODCS)", str(e))])

    checks += _required_checks(contract)
    if any(c.level == "error" for c in checks):
        return ValidationResult(checks)

    files: dict[str, str] = {}
    try:
        state = _state(text)
        state["transform_files"] = {}
        with contextlib.redirect_stdout(io.StringIO()):
            state.update(profiler_agent(state))
            state.update(naming_agent(state))

            fields = state["schema"]["fields"]
            names = {f["raw_field"]: {"staging_field": f["staging_field"], "comment": f["comment"]} for f in fields}
            errors, _ = validate_naming(fields, names)
            state.update(input_gen_agent(state))
            files.update(state["input_files"])
            files.update(transform_gen_agent(state)["transform_files"])
    except Exception as e:  # noqa: BLE001 — mostra o motivo na tela
        checks.append(Check("error", "Simulação da geração", str(e)))
        return ValidationResult(checks)

    if errors:
        detail = "; ".join(f"{e['raw_field']}: {e['message']}" for e in errors)
        checks.append(Check("error", "Padrão de nomenclatura", detail))
    else:
        checks.append(Check("ok", "Padrão de nomenclatura", ""))

    ingestion = yaml.safe_load(next(iter(state["input_files"].values())))
    pending = placeholders(ingestion)
    checks.append(Check("warning" if pending else "ok", "ingestion.yml completo",
                        f"Campos sem valor: {', '.join(pending)}" if pending else ""))
    checks.append(Check("ok", "Simulação da geração", f"{len(files)} arquivos"))
    return ValidationResult(checks, files)


# ── Etapa 4: geração ───────────────────────────────────────────────────

@dataclass
class GenerationResult:
    output_dir: Path
    contract_path: Path
    files: list[str]
    log: str
    published: list[str] = field(default_factory=list)


def generate(contract: dict, output_dir: str, llm_model: str = "", publish_s3: str = "") -> GenerationResult:
    """Grava o contrato em contracts/<dataset>/<tabela>.odcs.yaml e gera ingestion.yml + transformação."""
    from framework.graph import build_graph

    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = dump_contract(contract)
    table = contract["schema"][0]["name"]
    contract_path = out / "contracts" / contract["dataProduct"] / f"{table}.odcs.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(text, encoding="utf-8")

    state = _state(text, llm_model, naming_dir=str(out / "naming"), dry_run=False)
    state["output_dir"] = str(out)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        final = build_graph().invoke(state)

    published = []
    if publish_s3:
        from framework.publish import publish_to_s3
        for rel, content in final.get("input_files", {}).items():
            published.append(publish_to_s3(publish_s3, rel, content))

    files = sorted({**final.get("input_files", {}), **final.get("transform_files", {})})
    return GenerationResult(out, contract_path, files, buffer.getvalue(), published)
