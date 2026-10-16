---
name: error-handler
description: "Use when handling Spark errors, SparkException, AnalysisException, StreamingQueryException, JDBC/S3/HDFS connectivity failures, authorization failures, broadcast timeout, resource exhaustion, schema issues, or job configuration failures. Applies the classification and retry guidance defined in scripts/SparkErrorHandler.scala."
---

# Spark Error Handler

Use this skill whenever the task involves analyzing, classifying, explaining, or proposing remediation for Spark job failures.

## Source of Truth

Treat `scripts/SparkErrorHandler.scala` as the canonical reference for Spark error triage in this workspace.

Do not invent alternative categories if one of the categories below fits.

## Required Behavior

When a Spark-related error is presented:

1. Inspect the full causal chain, not only the top-level exception.
2. Map the failure to exactly one primary category from this skill.
3. State whether the error is retryable.
4. State whether it is a programming/configuration error.
5. Recommend the next action using the guidance below.
6. If the evidence is inconclusive, classify as `UnknownError` and say what logs or details are still needed.

## Classification Reference

### `ConnectivityError`

Use for network and connectivity failures such as:
- `ConnectException`
- `UnknownHostException`
- `SocketTimeoutException`
- `IOException` with connection, network, unreachable, S3, HDFS, or timeout indications
- `SQLException` with SQLState starting with `08`

Decision:
- `retryable = true`
- `programmingError = false`

Suggested action:
- Retry with exponential backoff.
- Verify DNS, endpoint availability, network path, firewall, S3/HDFS reachability, and JDBC target health.

### `ResourceExhaustionError`

Use for resource pressure and execution instability such as:
- `OutOfMemoryError`
- `SparkException` mentioning `GC overhead limit exceeded`
- `IOException` containing `No space left on device`
- shuffle fetch failures or `FetchFailed` conditions

Decision:
- `retryable = true`
- `programmingError = false`

Suggested action:
- Retry only with resource adjustment.
- Increase executor memory or cores, reduce partition size, review disk pressure, and inspect executor loss.

### `DataSchemaError`

Use for schema, query analysis, missing table, and type compatibility issues such as:
- `AnalysisException`
- `NoSuchTableException`
- `TreeNodeException`
- `SparkUpgradeException`

Decision:
- `retryable = false`
- `programmingError = true`

Suggested action:
- Do not recommend automatic retry.
- Fix schema definition, column names, query shape, table references, or data casting logic.

### `AuthorizationError`

Use for authentication and permission failures such as:
- Kerberos/authentication failures
- `403`
- `access denied`
- `permission denied`
- `SecurityException`
- ACL/IAM access control errors

Decision:
- `retryable = false`
- `programmingError = false`

Suggested action:
- Do not recommend automatic retry.
- Renew credentials or Kerberos ticket and fix IAM, ACL, or file permissions.

### `BroadcastTimeoutError`

Use when a `SparkException` indicates broadcast join timeout.

Decision:
- `retryable = true`
- `programmingError = false`

Suggested action:
- Increase `spark.sql.broadcastTimeout` or disable broadcast with `spark.sql.autoBroadcastJoinThreshold=-1`.

### `ConfigurationError`

Use for job setup and dependency failures such as:
- `ClassNotFoundException`
- `NoClassDefFoundError`
- `IllegalArgumentException`

Decision:
- `retryable = false`
- `programmingError = true`

Suggested action:
- Do not recommend automatic retry.
- Fix dependency packaging, `--jars`, `--packages`, or invalid runtime parameters.

### `UnknownError`

Use only when no rule above matches.

Decision:
- `retryable = false`
- `programmingError = false`

Suggested action:
- Request driver logs, executor logs, full stack trace, and the causal chain.

## Special Handling Rules

- For `StreamingQueryException`, inspect and classify the root cause instead of stopping at the streaming wrapper.
- For nested Spark failures, prioritize the most specific matching cause in the causal chain.
- Prefer the exact category names from this skill in your answer.
- If recommending retry, explain why the retry is expected to help.
- If not recommending retry, say what must be fixed before rerunning.

## Response Format

When answering a Spark error handling request, structure the response with these fields when possible:

- `Category`
- `Retryable`
- `Programming error`
- `Why`
- `Suggested action`
- `Additional evidence needed` if the classification is uncertain
