"""Utilitários de nomes compartilhados entre parsers e agentes."""

from __future__ import annotations

import re
import unicodedata


def strip_accents(text: str) -> str:
    """organização → organizacao"""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def split_tokens(name: str) -> list[str]:
    """createdAt / created_at / Created-At → ['created', 'at']"""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", strip_accents(name))
    return [t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if t]
