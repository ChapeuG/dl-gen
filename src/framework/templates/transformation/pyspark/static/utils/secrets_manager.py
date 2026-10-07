"""Recuperacao de segredos no AWS Secrets Manager. A regiao e extraida do ARN."""

from __future__ import annotations

import boto3


def get_secret_string(secret_arn: str) -> str:
    client = boto3.client("secretsmanager", region_name=secret_arn.split(":")[3])
    return client.get_secret_value(SecretId=secret_arn)["SecretString"]
