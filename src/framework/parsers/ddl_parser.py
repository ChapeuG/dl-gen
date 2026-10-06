"""Parser de DDL — extrai schema estruturado de um CREATE TABLE.

Suporta DDLs no formato:
    CREATE TABLE public.organizacao (
        id          uuid PRIMARY KEY,
        parent_id   uuid REFERENCES organizacao(id),
        name        VARCHAR(255) NOT NULL,
        ...
    );

Converte para FrameworkState.schema (SchemaInfo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from framework.standards.tipagem import TIPAGEM_OFICIAL, normalize_sql_type
from framework.state import FieldDef, SchemaInfo


# ── Mapeamento de tipos SQL → tipos Spark ──────────────────────────────

SPARK_TYPE_MAP: dict[str, str] = {
    "uuid": "StringType",
    "string": "StringType",
    "varchar": "StringType",
    "varchar2": "StringType",
    "nvarchar": "StringType",
    "character varying": "StringType",
    "character": "StringType",
    "text": "StringType",
    "char": "StringType",
    "boolean": "BooleanType",
    "bool": "BooleanType",
    "integer": "IntegerType",
    "int": "IntegerType",
    "int4": "IntegerType",
    "bigint": "LongType",
    "int8": "LongType",
    "smallint": "IntegerType",
    "int2": "IntegerType",
    "double": "DoubleType",
    "double precision": "DoubleType",
    "float8": "DoubleType",
    "real": "FloatType",
    "float4": "FloatType",
    "numeric": "DecimalType(19,2)",
    "decimal": "DecimalType(19,2)",
    "number": "DecimalType(19,2)",
    "date": "DateType",
    "timestamp": "TimestampType",
    "timestamp without time zone": "TimestampType",
    "timestamp with time zone": "TimestampType",
    "timestamptz": "TimestampType",
    "time": "StringType",
    "bytea": "StringType",
    "json": "StringType",
    "jsonb": "StringType",
}


@dataclass
class ParsedColumn:
    name: str
    raw_type: str
    spark_type: str
    nullable: bool
    is_pk: bool
    is_fk: bool
    comment: str


def _parse_type(raw_type: str, type_map: dict[str, str] | None = None) -> str:
    """Converte tipo SQL para tipo Spark.

    Prioridade: planilha (type_map) > tabela oficial TIPAGEM_OFICIAL > SPARK_TYPE_MAP.
    Arrays Postgres (text[]) viram ArrayType(<tipo>).
    """
    raw_lower = raw_type.lower().strip()
    if raw_lower.endswith("[]"):
        return f"ArrayType({_parse_type(raw_lower[:-2], type_map)})"

    raw_base = normalize_sql_type(raw_lower)
    mapping = {**SPARK_TYPE_MAP, **TIPAGEM_OFICIAL, **(type_map or {})}
    spark_type = mapping.get(raw_base, "StringType")

    # Numeric/Decimal com precisão explícita no DDL prevalece
    m = re.match(r"(?:numeric|decimal|number)\s*\((\d+)\s*,\s*(\d+)\)", raw_lower)
    if m and spark_type.startswith("DecimalType"):
        return f"DecimalType({m.group(1)},{m.group(2)})"
    if spark_type == "DecimalType":
        return "DecimalType(19,2)"
    return spark_type


def _split_top_level(body: str) -> list[str]:
    """Separa por vírgulas fora de parênteses e aspas (DECIMAL(10,2), COMMENT 'a, b')."""
    parts: list[str] = []
    depth = 0
    quote = ""
    current: list[str] = []
    for ch in body:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts


def _extract_body(ddl: str, start: int) -> tuple[str, int]:
    """Retorna o conteúdo entre o primeiro '(' após start e seu ')' correspondente."""
    open_idx = ddl.index("(", start)
    depth = 0
    quote = ""
    for i in range(open_idx, len(ddl)):
        ch = ddl[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return ddl[open_idx + 1:i], i
    raise ValueError("DDL com parênteses desbalanceados")


def _extract_comment(col_def: str) -> str:
    """Extrai COMMENT '...' de uma definição de coluna."""
    m = re.search(r"comment\s+'([^']*)'", col_def, re.IGNORECASE)
    if m:
        return m.group(1).replace('"', "'")
    return ""


def parse_ddl(ddl: str, dataset: str = "dataset", type_map: dict[str, str] | None = None) -> SchemaInfo:
    """Faz parse de um DDL CREATE TABLE e retorna SchemaInfo.

    Args:
        ddl: String com o DDL (CREATE TABLE ...).
        dataset: Nome do dataset (ex: vendas).
        type_map: Mapeamento tipo SQL → tipo Scala (planilha Tipagem.xlsx).

    Returns:
        SchemaInfo com table_name, source_table, fields, pk_fields, etc.
    """
    # Remove comentários de linha (-- ...)
    ddl = re.sub(r"--[^\n]*", "", ddl)

    # Extrai nome da tabela: CREATE TABLE [schema.]tabela (
    table_match = re.search(
        r"create\s+table\s+(?:if\s+not\s+exists\s+)?([^\s(]+)",
        ddl, re.IGNORECASE
    )
    if not table_match:
        raise ValueError("DDL não contém 'CREATE TABLE'")

    full_table = table_match.group(1)
    # source_table mantém o schema (ex: public.organizacao)
    source_table = full_table
    table_name = full_table.split(".")[-1].strip('"').strip("`")

    # Extrai o corpo entre parênteses (respeitando parênteses aninhados)
    try:
        body, body_end = _extract_body(ddl, table_match.end())
    except ValueError as e:
        raise ValueError("DDL não contém corpo entre parênteses") from e
    tail = ddl[body_end + 1:]

    # Comentário da tabela: ") COMMENT '...'" ou "COMMENT ON TABLE x IS '...'"
    table_comment = ""
    m = re.match(r"\s*comment\s*=?\s*'([^']*)'", tail, re.IGNORECASE) or re.search(
        r"comment\s+on\s+table\s+\S+\s+is\s+'([^']*)'", tail, re.IGNORECASE)
    if m:
        table_comment = m.group(1)

    # COMMENT ON COLUMN tabela.coluna IS '...'
    column_comments = {
        cm.group(1).split(".")[-1].strip('"'): cm.group(2)
        for cm in re.finditer(r"comment\s+on\s+column\s+(\S+)\s+is\s+'([^']*)'", tail, re.IGNORECASE)
    }

    # Separa em linhas de definição de coluna
    # Remove constraints de tabela (PRIMARY KEY (...), FOREIGN KEY (...), etc.)
    lines: list[str] = []
    for line in _split_top_level(body):
        line = line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("PRIMARY KEY") or upper.startswith("FOREIGN KEY") or upper.startswith("CONSTRAINT") or upper.startswith("UNIQUE") or upper.startswith("CHECK") or upper.startswith("INDEX"):
            continue
        lines.append(line)

    columns: list[ParsedColumn] = []
    pk_fields: list[str] = []

    for line in lines:
        # Nome da coluna (pode estar entre aspas duplas)
        col_match = re.match(r'"?(\w+)"?\s+(.+)', line)
        if not col_match:
            continue

        col_name = col_match.group(1)
        rest = col_match.group(2)

        # Tipo — primeira palavra (tipo base) + opcional (precisão)
        type_match = re.match(
            r"((?:double\s+precision|character\s+varying|timestamp\s+with(?:out)?\s+time\s+zone|\w+)(?:\s*\([^)]+\))?(?:\[\])?)",
            rest, re.IGNORECASE)
        raw_type = type_match.group(1).strip() if type_match else "string"
        spark_type = _parse_type(raw_type, type_map)

        # NOT NULL?
        nullable = "not null" not in rest.lower()

        # PRIMARY KEY inline?
        is_pk = "primary key" in rest.lower()
        if is_pk:
            pk_fields.append(col_name)

        # REFERENCES (FK)?
        is_fk = "references" in rest.lower()

        # COMMENT
        comment = _extract_comment(rest) or column_comments.get(col_name, "")

        columns.append(ParsedColumn(
            name=col_name,
            raw_type=raw_type,
            spark_type=spark_type,
            nullable=nullable,
            is_pk=is_pk,
            is_fk=is_fk,
            comment=comment,
        ))

    # Se não achou PK inline, procura por constraint separada
    if not pk_fields:
        pk_match = re.search(r"primary\s+key\s*\(([^)]+)\)", body, re.IGNORECASE)
        if pk_match:
            pk_fields = [c.strip().strip('"') for c in pk_match.group(1).split(",")]

    # Candidatos a partição (campos de data/timestamp)
    partition_candidates = [
        c.name for c in columns
        if c.spark_type in ("DateType", "TimestampType")
        and c.name in ("created_at", "dt_criacao", "dh_criacao", "dt_rfrn_mvmn")
        or (c.spark_type in ("DateType", "TimestampType") and "created" in c.name.lower())
    ]

    # Constrói FieldDef list
    fields: list[FieldDef] = []
    for col in columns:
        fields.append(FieldDef(
            raw_field=col.name,
            staging_field=col.name,  # o agente de nomenclatura aplica o padrão de nomenclatura
            raw_type=col.raw_type,
            data_type=col.spark_type,
            comment=col.comment or "",
            is_pk=col.name in pk_fields,
            is_fk=col.is_fk,
            nullable=col.nullable,
            encrypt=False,  # definido por --encrypt ou pelo arquivo de nomenclatura
        ))

    return SchemaInfo(
        table_name=table_name,
        source_table=source_table,
        dataset=dataset,
        table_comment=table_comment,
        fields=fields,
        pk_fields=pk_fields,
        partition_column="",  # definido pelo Profiler a partir de --partition-col
        merge_keys=[],        # definido pelo Profiler a partir de --merge-keys
        partition_candidates=partition_candidates,
    )
