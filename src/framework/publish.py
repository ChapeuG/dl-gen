"""Publicação do ingestion.yml no bucket S3 lido pelo ingestion-orchestrator."""

from __future__ import annotations

from framework.agents.input_gen import INGESTION_CONFIG_DIR


def _split_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"--publish-s3 precisa começar com s3:// (recebido: {uri})")
    bucket, _, prefix = uri[len("s3://"):].partition("/")
    if not bucket:
        raise ValueError(f"--publish-s3 sem bucket: {uri}")
    return bucket, prefix.strip("/")


def publish_to_s3(s3_prefix: str, rel_path: str, content: str) -> str:
    """Envia o arquivo para s3://bucket/prefixo/<dataset>/<tabela>.ingestion.yml e devolve a URI."""
    try:
        import boto3
    except ImportError as e:
        raise RuntimeError("--publish-s3 exige o boto3: pip install boto3") from e

    bucket, prefix = _split_s3_uri(s3_prefix)
    # rel_path = ingestion-config/<dataset>/<tabela>.ingestion.yml → <dataset>/<tabela>.ingestion.yml
    key_tail = rel_path.removeprefix(f"{INGESTION_CONFIG_DIR}/")
    key = f"{prefix}/{key_tail}" if prefix else key_tail
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=content.encode("utf-8"),
                                  ContentType="application/yaml")
    return f"s3://{bucket}/{key}"
