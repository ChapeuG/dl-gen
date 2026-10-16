"""Regras do padrão de nomenclatura — Padrões Para Criação de Objetos de Dados (Data Lake).

Usado de duas formas:
  - como contexto do prompt do agente de nomenclatura (texto integral do padrão);
  - como validação determinística dos nomes propostos (LLM, heurística ou arquivo).
"""

from __future__ import annotations

import re
from functools import lru_cache

from framework.skills import load_skill

# Quadro de Naturezas (abreviação → significado)
NATUREZAS: dict[str, str] = {
    "aa": "Ano",
    "cd": "Código",
    "dc": "Descrição",
    "dd": "Dia",
    "dh": "Data e horário",
    "dt": "Data",
    "hr": "Hora",
    "id": "Identificador",
    "in": "Indicador",
    "mm": "Mês",
    "mu": "Multimídia",
    "nm": "Nome",
    "nu": "Número",
    "pc": "Percentual",
    "qt": "Quantidade",
    "sg": "Sigla",
    "tx": "Texto",
    "vl": "Valor",
}

# Colunas de controle já geradas pelo template de transformação — não podem ser reutilizadas
RESERVED_STAGING: set[str] = {
    "dh_criacao_data_lake",
    "dh_criacao_registro",
    "dh_atualizacao_registro",
    "dt_criacao_data_lake_particao",
    "dt_criacao_registro_particao",
    "dt_atualizacao_registro_particao",
}

_NUMERIC = {"IntegerType", "LongType", "DoubleType", "FloatType", "ShortType", "ByteType"}

# Tipos esperados por natureza (divergência gera aviso, não erro)
EXPECTED_TYPES: dict[str, set[str]] = {
    "dt": {"DateType", "StringType"},
    "dh": {"TimestampType", "StringType"},
    "in": {"BooleanType", "StringType"},
    "vl": _NUMERIC | {"Decimal"},
    "pc": _NUMERIC | {"Decimal"},
    "qt": _NUMERIC | {"Decimal"},
}

# natureza + termo essencial + até 5 qualificadores (o padrão privilegia até 5)
MAX_TERMS = 6

STAGING_RE = re.compile(r"^[a-z]{2}(_[a-z0-9]+)+$")


@lru_cache(maxsize=1)
def load_padroes_text() -> str:
    """Texto do padrão de nomenclatura compactado (sem espaços repetidos nem seção de aprovações)."""
    text = load_skill("data-governance-names").reference("padrao_nomenclatura.txt").read_text(encoding="utf-8")
    cut = text.find("Controle e Histórico de Versões\nData")
    if cut > 0:
        text = text[:cut]
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def naturezas_table() -> str:
    return "\n".join(f"- {k}: {v}" for k, v in NATUREZAS.items())


def _type_matches(data_type: str, expected: set[str]) -> bool:
    return data_type in expected or ("Decimal" in expected and data_type.startswith("DecimalType"))


def validate_naming(fields: list[dict], names: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """Valida os nomes propostos contra o padrão de nomenclatura.

    Args:
        fields: FieldDef do schema (precisa de raw_field e data_type).
        names: raw_field → {"staging_field": ..., "comment": ...}

    Returns:
        (errors, warnings). Cada erro é {"raw_field", "message"} — o campo precisa ser renomeado.
    """
    errors: list[dict] = []
    warnings: list[str] = []
    seen: dict[str, str] = {}

    for f in fields:
        raw = f["raw_field"]
        entry = names.get(raw)
        if not entry or not entry.get("staging_field"):
            errors.append({"raw_field": raw, "message": "campo sem nome padronizado"})
            continue

        staging = entry["staging_field"]
        nat = staging.split("_", 1)[0]

        if not STAGING_RE.match(staging):
            errors.append({"raw_field": raw, "message": f"'{staging}' fora do formato natureza_termo[_qualificador] (minúsculo, sem acento)"})
        elif nat not in NATUREZAS:
            errors.append({"raw_field": raw, "message": f"'{staging}' usa natureza '{nat}' inexistente no Quadro de Naturezas"})

        if staging in RESERVED_STAGING:
            errors.append({"raw_field": raw, "message": f"'{staging}' é coluna de controle reservada do Data Lake"})

        if staging in seen:
            errors.append({"raw_field": raw, "message": f"'{staging}' duplicado (também usado por '{seen[staging]}')"})
        else:
            seen[staging] = raw

        if not entry.get("comment", "").strip():
            errors.append({"raw_field": raw, "message": "comentário vazio"})

        if len(staging.split("_")) > MAX_TERMS:
            warnings.append(f"{raw}: '{staging}' tem mais de 5 qualificadores")

        expected = EXPECTED_TYPES.get(nat)
        if expected and not _type_matches(f["data_type"], expected):
            warnings.append(f"{raw}: natureza '{nat}' com tipo {f['data_type']} — confira a natureza")

    return errors, warnings
