"""Parser de Data Contract (ODCS v3.x — https://bitol-io.github.io/open-data-contract-standard).

O contrato substitui o DDL e a maior parte das flags da CLI:

    dataProduct                          → dataset
    schema[].name / physicalName         → tabela / tabela de origem (schema.tabela)
    schema[].properties[]                → colunas (physicalType > logicalType para a tipagem)
    properties[].primaryKey (+Position)  → chave de merge do Delta
    properties[].partitioned             → coluna de partição (filtro incremental)
    properties[].customProperties        → encrypt, stagingName (extensões próprias)
    servers[].type                       → banco de origem (postgres, oracle, mysql, sqlserver)

As extensões próprias ficam em customProperties ([{property, value}]), como manda o padrão.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from framework.parsers.ddl_parser import _parse_type
from framework.state import FieldDef, SchemaInfo

SUPPORTED_API_VERSIONS = ("v3.0", "v3.1", "v3.2")

# logicalType do ODCS → tipo Spark (usado quando a coluna não tem physicalType)
LOGICAL_TYPE_MAP: dict[str, str] = {
    "string": "StringType",
    "integer": "LongType",
    "number": "DecimalType(38,10)",
    "boolean": "BooleanType",
    "date": "DateType",
    "timestamp": "TimestampType",
    "time": "StringType",
}

# Tipos de servidor do ODCS → preset de banco do framework
SERVER_TYPE_MAP: dict[str, str] = {
    "postgres": "postgres",
    "postgresql": "postgres",
    "oracle": "oracle",
    "mysql": "mysql",
    "sqlserver": "sqlserver",
}


@dataclass
class ContractTable:
    """Uma tabela do contrato, já resolvida para o framework."""
    contract: dict
    table: dict
    dataset: str
    source_db: str
    partition_col: str
    merge_keys: list[str]
    encrypt_columns: list[str]
    servers: list[dict] = field(default_factory=list)


def custom_props(obj: dict | None) -> dict:
    """customProperties ([{property, value}]) → dict."""
    props = (obj or {}).get("customProperties") or []
    return {p["property"]: p.get("value") for p in props if isinstance(p, dict) and "property" in p}


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in ("true", "sim", "yes", "1")


def column_name(prop: dict) -> str:
    """Nome da coluna na origem: physicalName (se houver) ou name."""
    return prop.get("physicalName") or prop["name"]


def load_contract(text: str) -> dict:
    """Lê o YAML do contrato e valida o mínimo exigido pelo framework."""
    contract = yaml.safe_load(text)
    if not isinstance(contract, dict):
        raise ValueError("Contrato inválido: o arquivo não é um objeto YAML")
    if contract.get("kind") != "DataContract":
        raise ValueError("Contrato inválido: 'kind' precisa ser DataContract (ODCS)")
    api = str(contract.get("apiVersion", ""))
    if not api.startswith(SUPPORTED_API_VERSIONS):
        raise ValueError(f"Contrato inválido: apiVersion '{api}' não suportada (use v3.x do ODCS)")
    if not contract.get("schema"):
        raise ValueError("Contrato inválido: 'schema' sem tabelas")
    for table in contract["schema"]:
        if not table.get("name") or not table.get("properties"):
            raise ValueError(f"Contrato inválido: tabela sem 'name' ou sem 'properties': {table.get('name')}")
        for prop in table["properties"]:
            if not prop.get("name"):
                raise ValueError(f"Contrato inválido: coluna sem 'name' na tabela {table['name']}")
    return contract


def select_table(contract: dict, table_name: str = "") -> dict:
    """Escolhe a tabela do contrato (obrigatório informar quando houver mais de uma)."""
    tables = contract["schema"]
    if table_name:
        match = next((t for t in tables if table_name.lower() in (t["name"].lower(), str(t.get("physicalName", "")).lower())), None)
        if match is None:
            raise ValueError(f"--table: '{table_name}' não existe no contrato. Tabelas: {', '.join(t['name'] for t in tables)}")
        return match
    if len(tables) > 1:
        raise ValueError(f"O contrato tem {len(tables)} tabelas; informe --table ({', '.join(t['name'] for t in tables)})")
    return tables[0]


def _source_db(servers: list[dict]) -> str:
    types = {SERVER_TYPE_MAP.get(str(s.get("type", "")).lower()) for s in servers}
    types.discard(None)
    if len(types) > 1:
        raise ValueError(f"Contrato com servidores de tipos diferentes: {sorted(types)}")
    return types.pop() if types else ""


def resolve_table(contract: dict, table_name: str = "") -> ContractTable:
    """Extrai do contrato as variáveis que hoje vêm por flag (dataset, banco, partição, merge, criptografia)."""
    table = select_table(contract, table_name)
    props = table["properties"]

    partitioned = sorted((p for p in props if p.get("partitioned")),
                         key=lambda p: p.get("partitionKeyPosition") or 0)
    pks = sorted((p for p in props if p.get("primaryKey")),
                 key=lambda p: p.get("primaryKeyPosition") or 0)

    servers = contract.get("servers") or []
    return ContractTable(
        contract=contract,
        table=table,
        dataset=str(contract.get("dataProduct") or contract.get("domain") or "").strip().lower().replace(" ", "_"),
        source_db=_source_db(servers),
        partition_col=column_name(partitioned[0]) if partitioned else "",
        merge_keys=[column_name(p) for p in pks],
        encrypt_columns=[column_name(p) for p in props if _truthy(custom_props(p).get("encrypt"))],
        servers=servers,
    )


def _spark_type(prop: dict, type_map: dict[str, str] | None) -> str:
    if prop.get("physicalType"):
        return _parse_type(str(prop["physicalType"]), type_map)
    logical = str(prop.get("logicalType", "string")).lower()
    return LOGICAL_TYPE_MAP.get(logical, "StringType")


def contract_to_schema(ct: ContractTable, dataset: str, type_map: dict[str, str] | None = None) -> SchemaInfo:
    """Converte a tabela do contrato no mesmo SchemaInfo produzido pelo parser de DDL."""
    table = ct.table
    pk_fields = list(ct.merge_keys)

    # Tabela de origem: physicalName da tabela, prefixado pelo schema do servidor quando não vier qualificado
    source_table = table.get("physicalName") or table["name"]
    server_schema = next((s.get("schema") for s in ct.servers if s.get("schema")), "")
    if "." not in source_table and server_schema:
        source_table = f"{server_schema}.{source_table}"

    fields: list[FieldDef] = []
    for prop in table["properties"]:
        raw = column_name(prop)
        extra = custom_props(prop)
        f = FieldDef(
            raw_field=raw,
            staging_field=raw,  # o agente de nomenclatura aplica o padrão de nomenclatura (stagingName do contrato prevalece)
            raw_type=str(prop.get("physicalType") or prop.get("logicalType") or "string"),
            data_type=_spark_type(prop, type_map),
            comment=str(prop.get("description") or "").strip().replace('"', "'"),
            is_pk=raw in pk_fields,
            is_fk=bool(prop.get("relationships")),
            nullable=not prop.get("required", False) and not prop.get("primaryKey", False),
            encrypt=False,  # aplicado pelo Profiler a partir de encrypt_columns
        )
        if extra.get("stagingName"):
            f["contract_staging_field"] = str(extra["stagingName"]).strip().lower()
        fields.append(f)

    partition_candidates = [f["raw_field"] for f in fields if f["data_type"] in ("DateType", "TimestampType")]

    return SchemaInfo(
        table_name=str(table["name"]),
        source_table=source_table,
        dataset=dataset,
        table_comment=str(table.get("description") or "").strip(),
        fields=fields,
        pk_fields=pk_fields,
        partition_column="",  # o Profiler valida e aplica
        merge_keys=[],
        partition_candidates=partition_candidates,
    )
