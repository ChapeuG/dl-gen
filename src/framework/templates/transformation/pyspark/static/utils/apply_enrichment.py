"""Helper para joins de enriquecimento com broadcast.

Encapsula o padrao de leitura de tabela Delta de dimensao, broadcast,
aliasing sequencial e join com o DataFrame principal.
"""

from __future__ import annotations

from functools import reduce

from pyspark.sql import DataFrame
from pyspark.sql.functions import broadcast, col, lit

from datalake.utils.dataframe_utils import rename_columns
from datalake.utils.enrichment import Enrichment
from datalake.utils.file_utils import get_s3_path_to_delta_table


def apply_enrichment(df: DataFrame, enrichment: Enrichment, s3_path: str, seq: int) -> DataFrame:
    """Aplica um join de enriquecimento com broadcast no DataFrame principal.

    Args:
        df:         DataFrame principal (fato)
        enrichment: Definicao do enrichment
        s3_path:    Caminho base S3 para construir o path da tabela lookup
        seq:        Contador sequencial para alias unico (delta1, delta2, ...)
    """
    if not enrichment.is_active:
        return df

    # 1. Construir path e selecionar apenas colunas necessarias (early projection)
    lookup_path = get_s3_path_to_delta_table(s3_path, enrichment.team, enrichment.dataset, enrichment.table)
    all_join_keys = [*enrichment.lookup_join_conditions, *enrichment.lookup_fixed_conditions,
                     *enrichment.lookup_conditional_conditions]
    select_cols = list(dict.fromkeys([*enrichment.lookup_column_list, *all_join_keys]))

    # 2. Broadcast: forca broadcast hash join para tabelas pequenas
    lookup_df = broadcast(df.sparkSession.read.format("delta").load(lookup_path).select(*select_cols))

    # 3. Aliasing: prefixo sequencial para evitar ambiguidade
    def alias(column: str) -> str:
        return f"delta{seq}_{column}"

    # Renomear colunas de resultado (aliases definidos no enrichment) e chaves de join com prefixo interno
    columns_to_rename = {k: v for k, v in enrichment.lookup_column_alias_list.items()
                         if k not in enrichment.lookup_join_conditions}
    keys_to_rename = {k: alias(k) for k in all_join_keys}
    renamed_lookup = rename_columns(lookup_df, {**columns_to_rename, **keys_to_rename})

    # 4. Construir condicao de join
    conditions = (
        [col(f"delta{seq}.{alias(k)}") == col(f"dataframe.{v}") for k, v in enrichment.lookup_join_conditions.items()]
        + [col(f"delta{seq}.{alias(k)}") == lit(v) for k, v in enrichment.lookup_fixed_conditions.items()]
        + [col(f"delta{seq}.{alias(k)}") == v for k, v in enrichment.lookup_conditional_conditions.items()]
    )
    condition = reduce(lambda a, b: a & b, conditions)

    # 5. Executar join
    result = df.alias("dataframe").join(renamed_lookup.alias(f"delta{seq}"), condition, enrichment.lookup_join_type)

    # 6. Renomear ou remover chaves temporarias
    rename_keys = {alias(k): enrichment.lookup_column_alias_list.get(k, alias(k)) for k in all_join_keys}
    result = rename_columns(result, rename_keys)
    return result.drop(*keys_to_rename.values())


def apply_all(df: DataFrame, join_seq: list[Enrichment], s3_path: str) -> DataFrame:
    """Aplica uma sequencia de enrichments sobre o DataFrame."""
    seq = 1
    for enrichment in join_seq:
        df = apply_enrichment(df, enrichment, s3_path, seq)
        if enrichment.is_active:
            seq += 1
    return df
