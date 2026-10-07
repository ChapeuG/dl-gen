"""Parsing de argumentos de linha de comando no formato ``--chave valor``, sem ordem fixa."""

from __future__ import annotations


def parse(args: list[str]) -> dict[str, str]:
    """Converte uma lista de argumentos ``--chave valor`` em um mapa ``chave -> valor`` (sem o ``--``)."""
    return {key[2:]: value for key, value in zip(args[::2], args[1::2]) if key.startswith("--")}
