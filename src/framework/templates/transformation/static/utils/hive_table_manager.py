"""Gerenciamento de tabelas Hive/Athena externas para Delta Lake.

Cobre criacao de tabela com symlink manifest, mapeamento de tipos Spark->Hive,
schema evolution e registro incremental de particoes.

Substitui o uso de ``MSCK REPAIR TABLE`` por operacoes diretas e incrementais.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import (BinaryType, BooleanType, DataType, DateType, DecimalType, DoubleType, FloatType,
                               IntegerType, LongType, StringType, StructField, StructType, TimestampType)

#: Maximo de particoes por statement ALTER TABLE ADD PARTITION.
#: Evita estourar limites de tamanho de query no metastore (Glue/Hive).
PARTITION_BATCH_SIZE = 100

_HIVE_TYPES = {StringType: "string", IntegerType: "int", LongType: "bigint", DoubleType: "double",
               FloatType: "float", BooleanType: "boolean", DateType: "date", TimestampType: "timestamp",
               BinaryType: "binary"}


def spark_to_hive_type(dt: DataType) -> str:
    """Mapeia DataType do Spark para tipo Hive equivalente."""
    if isinstance(dt, DecimalType):
        return f"decimal({dt.precision},{dt.scale})"
    return _HIVE_TYPES.get(type(dt), "string")


def get_column_comment(field_name: str, column_comments: dict[str, str]) -> str:
    """Fragmento DDL de comentario para coluna, truncado em 255 caracteres."""
    comment = column_comments.get(field_name, "")
    return f' COMMENT "{comment[:255]}"' if comment else ""


def _column_ddl(f: StructField, column_comments: dict[str, str]) -> str:
    return f"`{f.name.replace('.', '_')}` {spark_to_hive_type(f.dataType)}{get_column_comment(f.name, column_comments)}"


def create_table(
    spark: SparkSession,
    table_name: str,
    schema: StructType,
    partitions: list[str],
    output_path: str,
    table_comment: str = "",
    column_comments: dict[str, str] | None = None,
    database: str = "",
) -> None:
    """Cria tabela externa Hive apontando para o manifesto symlink do Delta.

    Args:
        table_name:      Nome completo da tabela (database.table)
        schema:          Schema do DataFrame (inclui todas as colunas)
        partitions:      Nomes das colunas de particao
        output_path:     Caminho raiz da tabela Delta
        table_comment:   Comentario da tabela (truncado em 255 chars)
        column_comments: Comentarios por coluna
        database:        Nome do database Hive
    """
    column_comments = column_comments or {}
    if database:
        spark.sql(f"use {database}")

    part_set = set(partitions)
    columns_ddl = ",\n    ".join(_column_ddl(f, column_comments) for f in schema.fields if f.name not in part_set)
    partition_ddl = ", ".join(_column_ddl(f, column_comments) for f in schema.fields if f.name in part_set)

    manifest_path = output_path + "/_symlink_format_manifest/"
    table_comment_ddl = f"COMMENT '{table_comment[:255]}'" if table_comment else ""

    spark.sql(f"""CREATE EXTERNAL TABLE IF NOT EXISTS {table_name} (
    {columns_ddl}
)
{table_comment_ddl}
PARTITIONED BY ({partition_ddl})
ROW FORMAT SERDE 'org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe'
STORED AS INPUTFORMAT 'org.apache.hadoop.hive.ql.io.SymlinkTextInputFormat'
  OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION '{manifest_path}'""")


def evolve_schema(
    spark: SparkSession,
    table_name: str,
    schema_fields: list[StructField],
    column_comments: dict[str, str] | None = None,
) -> None:
    """Detecta colunas novas no schema (excluindo particoes) e adiciona via ALTER TABLE."""
    column_comments = column_comments or {}
    existing_cols = {c.name for c in spark.catalog.listColumns(table_name)}
    for f in schema_fields:
        if f.name not in existing_cols:
            spark.sql(f"ALTER TABLE {table_name} ADD COLUMNS (\n    {_column_ddl(f, column_comments)}\n)")


def register_partitions(spark: SparkSession, table_name: str, df: DataFrame, partition_fields: list[str]) -> None:
    """Registra as particoes do batch atual via ALTER TABLE ADD PARTITION em lote.

    Substitui MSCK REPAIR TABLE, que escaneia todas as particoes existentes.
    Aceita qualquer numero de niveis de particao (1, 2, ou mais).
    """
    partition_values = df.select(*partition_fields).distinct().collect()

    for i in range(0, len(partition_values), PARTITION_BATCH_SIZE):
        batch = partition_values[i:i + PARTITION_BATCH_SIZE]
        clauses = "\n    ".join(
            "PARTITION (" + ", ".join(f"{name}='{row[idx]}'" for idx, name in enumerate(partition_fields)) + ")"
            for row in batch
        )
        spark.sql(f"ALTER TABLE {table_name} ADD IF NOT EXISTS\n    {clauses}")
