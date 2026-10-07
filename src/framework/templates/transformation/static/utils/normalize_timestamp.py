"""Normalizacao de strings de timestamp antes da conversao para TimestampType via ``to_timestamp``.

Trata inconsistencias comuns em dados brutos:
- Espacos extras entre data e hora
- Ausencia do separador "T" (ISO 8601)
- Uso de "/" ao inves de "-" como separador de data

Nao altera o valor temporal — apenas normaliza o formato para que ``to_timestamp``
consiga parsear. Feito com expressoes nativas (sem UDF Python), entao roda na JVM
sem serializacao para o worker Python.
"""

from __future__ import annotations

from pyspark.sql import Column
from pyspark.sql.functions import concat, instr, length, lit, regexp_replace, upper, when


def normalize_timestamp_string(c: Column) -> Column:
    """Normaliza uma string de timestamp para formato ISO 8601 compativel.

    Transformacoes aplicadas:
    1. Remove todos os espacos
    2. Insere "T" entre data e hora se ausente (para strings >= 18 chars)
    3. Substitui "/" por "-" no separador de data

    Retorna o valor original se a string for null ou tiver menos de 18 caracteres
    (formato curto, sem hora completa).

    Uso::

        from pyspark.sql.functions import col, to_timestamp
        df.withColumn("ts", to_timestamp(normalize_timestamp_string(col("raw_ts"))))
        df.withColumn("ts", to_timestamp(normalize_timestamp_string(col("raw_ts")), "yyyy-MM-dd'T'HH:mm:ss"))
    """
    trimmed = upper(regexp_replace(c, " ", ""))
    with_t = when(instr(trimmed, "T") == 0,
                  concat(trimmed.substr(1, 10), lit("T"), trimmed.substr(11, 1_000_000))).otherwise(trimmed)
    return when(length(trimmed) >= 18, regexp_replace(with_t, "/", "-")).otherwise(c)
