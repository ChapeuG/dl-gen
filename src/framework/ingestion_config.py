"""Gera o ingestion.yml (formato ingestion/v1) lido pelo ingestion-orchestrator.

O yml é a parte do data contract que o motor de ingestão precisa para rodar:
origem (conector + servidores por ambiente), carga (incremental/full, paralelismo),
colunas, criptografia, destino na raw e regras de qualidade.

Valores com {env} são resolvidos pelo orquestrador em tempo de execução (--env dev|hml|prd).
O destino na raw não fica no yml: é sempre <--raw-bucket>/<dataset>/<tabela>/ (montado pelo orquestrador).
Sem contrato (entrada por DDL), o que não pode ser inferido sai como PREENCHER.
"""

from __future__ import annotations

import yaml

from framework.parsers.contract_parser import column_name, custom_props, load_contract, resolve_table
from framework.state import SchemaInfo

API_VERSION = "ingestion/v1"
PLACEHOLDER = "PREENCHER"

DEFAULT_FETCH_SIZE = 150000
DEFAULT_CRYPTO_FIELD = "AES_KEY"

# Spark → tipo lógico do yml (o orquestrador só usa para conferência e documentação)
_LOGICAL = {
    "StringType": "string", "BooleanType": "boolean", "IntegerType": "integer", "LongType": "integer",
    "ShortType": "integer", "ByteType": "integer", "DoubleType": "number", "FloatType": "number",
    "DateType": "date", "TimestampType": "timestamp", "BinaryType": "binary",
}


def _logical(spark_type: str) -> str:
    if spark_type.startswith("DecimalType"):
        return "number"
    if spark_type.startswith("ArrayType"):
        return "array"
    return _LOGICAL.get(spark_type, "string")


def _servers(contract_servers: list[dict]) -> dict:
    """servers[] do contrato → {ambiente: {host, port, database, secretId}}."""
    result: dict = {}
    for s in contract_servers:
        env = str(s.get("environment") or s.get("server") or "default").lower()
        extra = custom_props(s)
        result[env] = {k: v for k, v in {
            "host": s.get("host"),
            "port": s.get("port"),
            "database": s.get("database") or s.get("serviceName"),
            "secretId": extra.get("secretId") or PLACEHOLDER,
        }.items() if v is not None}
    return result


def _quality(table: dict) -> list[dict]:
    """Regras de qualidade do ODCS que o orquestrador executa (as demais ficam para o datacontract-cli)."""
    rules: list[dict] = []

    def _translate(q: dict, column: str | None):
        metric = q.get("metric")
        severity = "error" if str(q.get("severity", "error")).lower() == "error" else "warning"
        if metric == "nullValues" and column and q.get("mustBe", 0) == 0:
            rules.append({"check": "notNull", "columns": [column], "severity": severity})
        elif metric == "duplicateValues" and q.get("mustBe", 0) == 0:
            cols = [column] if column else list(q.get("arguments", {}).get("properties", []))
            if cols:
                rules.append({"check": "unique", "columns": cols, "severity": severity})
        elif metric == "rowCount":
            bounds = {k: q[k] for k in ("mustBeGreaterThan", "mustBeGreaterOrEqualTo", "mustBeLessThan",
                                        "mustBeLessOrEqualTo") if k in q}
            if bounds:
                rules.append({"check": "rowCount", **bounds, "severity": severity})

    for prop in table.get("properties", []):
        for q in prop.get("quality") or []:
            _translate(q, column_name(prop))
    for q in table.get("quality") or []:
        _translate(q, None)
    return rules


def build_ingestion_config(schema: SchemaInfo, source_db: str, contract_text: str = "",
                           contract_table: str = "", partition_col: str = "",
                           extra_incremental: list[str] | None = None) -> dict:
    """Monta o dicionário do ingestion.yml a partir do schema (já processado) e do contrato."""
    dataset = schema["dataset"]
    table_name = schema["table_name"]
    fields = schema["fields"]

    contract: dict = {}
    table: dict = {}
    servers: dict = {"prd": {"host": PLACEHOLDER, "port": PLACEHOLDER, "database": PLACEHOLDER,
                             "secretId": PLACEHOLDER}}
    if contract_text:
        ct = resolve_table(load_contract(contract_text), contract_table)
        contract, table = ct.contract, ct.table
        if ct.servers:
            servers = _servers(ct.servers)

    tprops = custom_props(table)
    partition_col = partition_col or schema.get("partition_column", "")
    encrypted = [f["raw_field"] for f in fields if f.get("encrypt")]

    load_mode = str(tprops.get("loadMode") or ("incremental" if partition_col else "full")).lower()
    if load_mode == "incremental" and not partition_col:
        raise ValueError(f"loadMode incremental exige uma coluna partitioned: true na tabela {table_name}")
    extra_cols = list(tprops.get("incrementalColumns") or []) + list(extra_incremental or [])
    incremental_cols = list(dict.fromkeys([partition_col] + extra_cols)) if partition_col else []

    config: dict = {
        "apiVersion": API_VERSION,
        "kind": "Ingestion",
        "contract": {
            "id": contract.get("id", PLACEHOLDER if contract_text else "sem-contrato"),
            "version": str(contract.get("version", "0.0.0")),
            "status": contract.get("status", "draft"),
        },
        "dataset": dataset,
        "table": table_name,
        "description": schema.get("table_comment", ""),
        "source": {
            "type": source_db,
            "table": schema["source_table"],
            "servers": servers,
        },
        "load": {
            "mode": load_mode,
            "incrementalColumns": incremental_cols if load_mode == "incremental" else [],
            "fetchSize": int(tprops.get("fetchSize") or DEFAULT_FETCH_SIZE),
            "parallel": {
                "days": int(tprops.get("numDaysParallel") or 1),
                "queries": int(tprops.get("numQueriesParallel") or 1),
                "column": tprops.get("parallelismColumn") or partition_col,
            },
        },
        "columns": [
            {k: v for k, v in {
                "name": f["raw_field"],
                "type": _logical(f["data_type"]),
                "physicalType": f["raw_type"],
                "primaryKey": f["is_pk"] or None,
                "required": (not f["nullable"]) or None,
                "encrypt": f.get("encrypt") or None,
            }.items() if v is not None}
            for f in fields
        ],
        "target": {
            "database": tprops.get("rawDatabase") or f"raw_{dataset}",
            "table": tprops.get("rawTable") or table_name,
            "partitionColumn": tprops.get("rawPartitionColumn") or PLACEHOLDER,  # obrigatório no contrato
            "format": "json",
            "compression": "gzip",
        },
    }

    if encrypted:
        config["encryption"] = {
            "algorithm": "AES/ECB",
            "secretArn": tprops.get("cryptographySecretArn") or PLACEHOLDER,
            "secretField": tprops.get("cryptographySecretField") or DEFAULT_CRYPTO_FIELD,
            "columns": encrypted,
        }

    quality = _quality(table) if table else []
    if quality:
        config["quality"] = quality

    return config


def dump_ingestion_config(config: dict) -> str:
    header = (
        "# Gerado pelo dl-gen a partir do data contract. Não edite à mão: altere o contrato e gere de novo.\n"
        "# Lido pelo ingestion-orchestrator (valores com {env} são resolvidos por --env).\n"
    )
    return header + yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=120)


def placeholders(config: dict) -> list[str]:
    """Caminhos do yml que ainda estão como PREENCHER."""
    found: list[str] = []

    def _walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and PLACEHOLDER in node:
            found.append(path)

    _walk(config, "")
    return found
