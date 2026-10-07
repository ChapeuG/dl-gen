"""Utilitários de nomes compartilhados entre parsers e agentes."""

from __future__ import annotations

import re
import unicodedata

SCALA_KEYWORDS = {
    "type", "class", "object", "val", "var", "def", "if", "else", "match", "case",
    "for", "while", "do", "true", "false", "null", "return", "yield", "throw", "try",
    "catch", "finally", "import", "package", "trait", "extends", "with", "new",
    "abstract", "final", "private", "protected", "override", "super", "this",
    "implicit", "lazy", "sealed", "forSome",
}


def strip_accents(text: str) -> str:
    """organização → organizacao"""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def split_tokens(name: str) -> list[str]:
    """createdAt / created_at / Created-At → ['created', 'at']"""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", strip_accents(name))
    return [t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if t]


def snake_to_camel(snake: str) -> str:
    """dh_criacao_registro → dhCriacaoRegistro"""
    parts = [p for p in snake.split("_") if p]
    if not parts:
        return snake
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def scala_identifier(snake: str) -> str:
    """Nome snake_case → identificador Scala válido (camelCase, keywords com backticks)."""
    camel = snake_to_camel(snake)
    if camel in SCALA_KEYWORDS or not re.match(r"[A-Za-z_]", camel):
        return f"`{camel}`"
    return camel
