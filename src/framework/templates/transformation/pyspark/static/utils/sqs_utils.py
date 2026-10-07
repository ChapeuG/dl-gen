"""Envio de mensagens de erro a filas SQS.

Converte um SparkErrorResult em um payload JSON estruturado e o entrega
a fila identificada pelo ARN fornecido.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import boto3

from datalake.error.spark_error_handler import SparkErrorResult


def send_error(sqs_arn: str, result: SparkErrorResult, context: dict[str, str]) -> None:
    _, _, _, region, account_id, queue_name = sqs_arn.split(":")[:6]
    queue_url = f"https://sqs.{region}.amazonaws.com/{account_id}/{queue_name}"
    client = boto3.client("sqs", region_name=region)
    client.send_message(QueueUrl=queue_url, MessageBody=build_payload(result, context))


def build_payload(result: SparkErrorResult, context: dict[str, str]) -> str:
    error = result.original_error
    return json.dumps({
        "errorCategory": result.category.name,
        "description": result.category.description,
        "retryable": result.retryable,
        "programmingError": result.programming_error,
        "suggestedAction": result.suggested_action,
        "errorMessage": str(error),
        "errorClass": f"{type(error).__module__}.{type(error).__qualname__}",
        "context": {**context, "timestamp": datetime.now(timezone.utc).isoformat()},
    }, indent=2, ensure_ascii=False)
