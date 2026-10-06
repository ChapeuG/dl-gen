"""Profiler de amostra — analisa N linhas e extrai perfil estatístico.

Detecta: tipos inferidos, nulos, cardinalidade, valores em centavos,
padrões de string, PII potencial.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from framework.state import ProfileField, ProfileInfo


# Padrões que indicam PII
PII_PATTERNS = {
    "cpf": re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$"),
    "cnpj": re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$"),
    "email": re.compile(r"^[\w.-]+@[\w.-]+\.\w+$"),
    "phone": re.compile(r"^\+?\d{10,13}$"),
    "card": re.compile(r"^\d{13,19}$"),
    "uuid": re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE),
}

# Nomes de coluna que sugerem PII
PII_COLUMN_NAMES = {
    "cpf", "cnpj", "email", "phone", "telefone", "card", "cartao",
    "pan", "token", "password", "senha", "secret", "hash",
    "nu_cpf", "nu_cnpj", "nu_cartao", "document", "documento",
}


def _looks_like_cents(series: pd.Series) -> bool:
    """Detecta se valores inteiros parecem estar em centavos.

    Heurística: se são inteiros, não têm decimal, e a maioria é > 1000
    com média alta, provavelmente são centavos (19999 em vez de 199.99).
    """
    if series.dtype not in ("int64", "int32", "Int64"):
        return False
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    # Se todos são divisíveis por 100 e a média > 100, provável centavos
    if (non_null % 100 == 0).mean() > 0.7 and non_null.mean() > 100:
        return True
    return False


def looks_like_pii_name(name: str) -> bool:
    """Detecta PII só pelo nome da coluna (usado sem amostra)."""
    col_lower = name.lower()
    return any(pii_name in col_lower for pii_name in PII_COLUMN_NAMES)


def _detect_pii(name: str, series: pd.Series) -> bool:
    """Detecta se a coluna parece conter PII."""
    # Por nome de coluna
    if looks_like_pii_name(name):
        return True

    # Por padrão nos valores
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    sample = non_null.head(100).astype(str)
    for pattern in PII_PATTERNS.values():
        matches = sample.str.match(pattern).sum()
        if matches / len(sample) > 0.5:
            return True

    return False


def _infer_type(series: pd.Series) -> str:
    """Infere tipo Spark a partir dos dados."""
    if series.dtype in ("int64", "int32", "Int64"):
        return "IntegerType"
    if series.dtype in ("float64", "float32", "Float64"):
        return "DoubleType"
    if series.dtype == "bool":
        return "BooleanType"
    # Tenta datetime
    try:
        pd.to_datetime(series.dropna().head(10))
        return "TimestampType"
    except (ValueError, TypeError):
        pass
    return "StringType"


def profile_sample(sample_path: str) -> ProfileInfo:
    """Faz profiling de uma amostra de dados.

    Args:
        sample_path: Caminho para CSV/JSON/Parquet com N linhas.

    Returns:
        ProfileInfo com perfil estatístico por campo.
    """
    path = Path(sample_path)
    suffix = path.suffix.lower()

    # Detecta parquet sem extensão pelo magic header (PAR1)
    def _is_parquet(p: Path) -> bool:
        try:
            with open(p, "rb") as f:
                return f.read(4) == b"PAR1"
        except (OSError, IOError):
            return False

    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix == ".json":
        df = pd.read_json(path, lines=True)
    elif suffix == ".parquet" or _is_parquet(path):
        df = pd.read_parquet(path)
    else:
        # Tenta CSV por padrão
        df = pd.read_csv(path)

    row_count = len(df)
    fields: list[ProfileField] = []
    monetary_fields: list[str] = []

    for col in df.columns:
        series = df[col]
        non_null = series.dropna()

        null_count = int(series.isna().sum())
        null_pct = null_count / row_count if row_count > 0 else 0.0
        cardinality = int(non_null.nunique())
        unique_pct = cardinality / row_count if row_count > 0 else 0.0

        # Min/max como string
        min_val = str(non_null.min()) if len(non_null) > 0 else None
        max_val = str(non_null.max()) if len(non_null) > 0 else None

        looks_cents = _looks_like_cents(series)
        looks_pii = _detect_pii(col, series)

        # Valores de exemplo (até 5)
        sample_values = [str(v) for v in non_null.head(5).tolist()]

        inferred = _infer_type(series)

        fields.append(ProfileField(
            name=col,
            inferred_type=inferred,
            null_count=null_count,
            null_pct=round(null_pct, 4),
            cardinality=cardinality,
            unique_pct=round(unique_pct, 4),
            min_value=min_val,
            max_value=max_val,
            looks_like_cents=looks_cents,
            looks_like_pii=looks_pii,
            sample_values=sample_values,
        ))

        if looks_cents:
            monetary_fields.append(col)

    return ProfileInfo(
        row_count=row_count,
        fields=fields,
        has_monetary_fields=len(monetary_fields) > 0,
        monetary_fields=monetary_fields,
    )
