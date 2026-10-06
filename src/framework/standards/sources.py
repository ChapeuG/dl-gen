"""Bancos de origem suportados e os ajustes de tipagem de cada um.

Driver, URL e filtro de data ficam nos conectores do ingestion-orchestrator; aqui só importa
como cada banco mapeia seus tipos para o Spark (ex: DATE do Oracle tem hora → TimestampType).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceDb:
    name: str
    # Ajustes de tipo (tipo SQL normalizado → tipo Spark) específicos do banco
    type_overrides: dict[str, str] = field(default_factory=dict)


SOURCES: dict[str, SourceDb] = {
    "postgres": SourceDb(name="postgres"),
    "oracle": SourceDb(
        name="oracle",
        # O conector lê com mapDateToTimestamp: o DATE do Oracle (que tem hora) vira timestamp
        type_overrides={
            "date": "TimestampType",
            "number": "DecimalType(38,10)",
            "varchar2": "StringType",
            "nvarchar2": "StringType",
            "clob": "StringType",
            "raw": "BinaryType",
        },
    ),
    "mysql": SourceDb(
        name="mysql",
        type_overrides={"tinyint": "IntegerType", "mediumint": "IntegerType", "longtext": "StringType"},
    ),
    "sqlserver": SourceDb(
        name="sqlserver",
        type_overrides={
            "bit": "BooleanType",
            "datetime2": "TimestampType",
            "smalldatetime": "TimestampType",
            "uniqueidentifier": "StringType",
            "nvarchar": "StringType",
            "money": "DecimalType(19,4)",
        },
    ),
}


def get_source(name: str = "postgres") -> SourceDb:
    key = (name or "postgres").lower()
    if key not in SOURCES:
        raise ValueError(f"Banco de origem '{name}' não suportado. Opções: {', '.join(SOURCES)}")
    return SOURCES[key]
