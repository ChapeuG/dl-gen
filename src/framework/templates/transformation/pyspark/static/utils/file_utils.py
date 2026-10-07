"""Construcao e derivacao de paths S3 no padrao ``s3://<bucket>/<team>/<dataset>/<table>``."""

from __future__ import annotations


def derive_base_path_from_table_uri(table_uri: str) -> str:
    """Deriva o base path (``s3://<bucket>``) removendo os tres ultimos segmentos (``team/dataset/table``)."""
    normalized = table_uri.rstrip("/")
    scheme_end = normalized.index("://") + 3
    segments = normalized[scheme_end:].split("/")
    if len(segments) < 4:
        raise ValueError(f"output_uri fora do padrao s3://<bucket>/<team>/<dataset>/<table>: {table_uri}")
    return normalized[:scheme_end] + "/".join(segments[:-3])


def get_s3_path_to_delta_table(base_path: str, team: str, dataset: str, table: str) -> str:
    """Path da tabela Delta de lookup: ``<basePath>/<team>/<dataset>/<table>``."""
    return f"{base_path.rstrip('/')}/{team}/{dataset}/{table}"
