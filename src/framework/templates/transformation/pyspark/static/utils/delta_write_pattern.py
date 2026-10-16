"""Padroes canonicos de escrita Delta Lake.

Centraliza a logica de decisao entre overwrite (primeira carga) e merge
incremental (upsert), com deduplicacao pre-merge, file sizing otimizado e
geracao de manifesto para Athena.
"""

from __future__ import annotations

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql.functions import col, row_number


def dedup(df: DataFrame, merge_keys: list[str], timestamp_column: str) -> DataFrame:
    """Mantem apenas o registro mais recente por chave de merge.

    Usa Window + row_number para garantir, de forma deterministica, que o registro com maior
    ``timestamp_column`` por chave seja mantido. O padrao orderBy + dropDuplicates NAO oferece
    essa garantia: dropDuplicates re-particiona pelas chaves e descarta a ordenacao global,
    mantendo um registro arbitrario por grupo.
    """
    w = Window.partitionBy(*[col(k) for k in merge_keys]).orderBy(col(timestamp_column).desc())
    return df.withColumn("__rn", row_number().over(w)).filter(col("__rn") == 1).drop("__rn")


def save(
    spark: SparkSession,
    df: DataFrame,
    output_path: str,
    merge_conditions: dict[str, str],
    partitions: list[str],
    avg_row_size: int = 340,
) -> None:
    """Persiste o DataFrame em Delta Lake com estrategia automatica:
    - Primeira carga: overwrite com particionamento e file sizing
    - Cargas subsequentes: merge incremental com condicoes null-safe

    Args:
        merge_conditions: {coluna_source: coluna_target} da condicao de merge
        avg_row_size:     Tamanho medio de uma linha em bytes (para calculo de maxRecordsPerFile)
    """
    is_delta = DeltaTable.isDeltaTable(spark, output_path)

    # Adaptive file sizing para overwrite e MERGE — evita small files sem risco de OOM em particoes grandes
    spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "true")

    if is_delta:
        # Configs de otimizacao para merge
        spark.conf.set("spark.databricks.delta.merge.optimizeInsertOnlyMerge.enabled", "true")
        spark.conf.set("spark.databricks.delta.merge.repartitionBeforeWrite.enabled", "true")
        spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")

        # Condicao null-safe com <=>
        conditions = " and ".join(f"s.`{src}` <=> t.`{tgt}`" for src, tgt in merge_conditions.items())
        update_assignments = {f"`{c}`": col(f"s.`{c}`") for c in df.columns if c != "dh_criacao_registro"}

        (DeltaTable.forPath(spark, output_path).alias("t")
            .merge(df.alias("s"), conditions)
            .whenMatchedUpdate(set=update_assignments)
            .whenNotMatchedInsertAll()
            .execute())
    else:
        # Primeira carga: overwrite com file sizing
        nr_rows = (128 * 1024 * 1024) // avg_row_size

        (df.write
            .mode("overwrite")
            .format("delta")
            .option("delta.autoOptimize.optimizeWrite", "true")
            .option("maxRecordsPerFile", nr_rows)
            .partitionBy(*partitions)
            .save(output_path))

    # Gerar manifesto para Athena
    DeltaTable.forPath(spark, output_path).generate("symlink_format_manifest")
