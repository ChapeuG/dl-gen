---
name: data-transformation-patterns
description: "Use when defining, reviewing, generating, or refactoring Spark DataFrame transformations in Scala, especially for string normalization, AES-encrypted string handling, date parsing, and timestamp preservation rules. Applies canonical transformation patterns for Spark columns in this workspace."
---

# Spark Data Transformation Patterns

Use this skill whenever the task involves creating or reviewing Spark DataFrame transformations in Scala.

## Purpose

This skill defines the canonical transformation rules for DataFrame columns in Spark.

When generating code, reviewing logic, or proposing refactors, prefer these rules over ad hoc transformations.

## Required Behavior

When working on Spark DataFrame transformations in Scala:

1. Identify the logical data type and business treatment of each column before proposing a transformation.
2. Apply the exact pattern from this skill for `String`, encrypted `String`, `Date`, and `Timestamp` fields.
3. Any information classified as PII must be protected with encryption.
4. Whenever encryption is required, obtain the encryption key from AWS Secrets Manager using the ARN received as a job parameter.
5. Do not apply case normalization blindly across all text columns.
6. Preserve semantic correctness before formatting convenience.
7. If a required input format for `Date` is missing, ask for it before finalizing the transformation.
8. For `Timestamp`, preserve the original value and do not propose timezone-based conversions unless the user explicitly changes the rule.

## Canonical Patterns

### Standard `String`

Rule:
- Apply `TRIM` and `UPPERCASE`.

Intent:
- Remove leading and trailing whitespace.
- Normalize textual comparison and storage using uppercase.

Scala Spark guidance:
- Prefer `trim(col("field"))` followed by `upper(...)`.
- Equivalent pattern: `upper(trim(col("field")))`.

Default example:

```scala
import org.apache.spark.sql.functions.{col, trim, upper}

df.withColumn("name", upper(trim(col("name"))))
```

### Encrypted `String` with AES

Rule:
- Apply `TRIM` before encryption.
- Preserve case sensitivity.
- Do not apply `UPPER` or any other case transformation.

PII rule:
- Any field classified as PII must be routed through encryption.
- If the PII field is textual, apply `TRIM` before encryption and preserve the original case.
- The encryption key must be retrieved from AWS Secrets Manager using an ARN provided by parameter.

Intent:
- Normalize accidental whitespace without changing the source value semantics before encryption.
- Avoid changing the encrypted output because of artificial case normalization.
- Ensure sensitive personal data is not persisted or exposed in plain text.

Scala Spark guidance:
- Trim the original column first.
- Resolve the Secrets Manager ARN from the input parameter.
- Retrieve the secret value from AWS Secrets Manager before invoking the encryption routine.
- Pass the trimmed value into the AES encryption function.
- Keep original character casing intact.

Default example:

```scala
import org.apache.spark.sql.functions.{col, trim}

df.withColumn("document_encrypted", aes_encrypt(trim(col("document")), col("secret_key")))
```

If `aes_encrypt` is not the function already used in the codebase, preserve the existing encryption primitive and only enforce the pre-encryption `trim` rule plus secret retrieval via AWS Secrets Manager.

### PII

Rule:
- Any information classified as PII must be encrypted before persistence, publication, or downstream exposure.

Intent:
- Protect sensitive data by preventing storage or propagation in plain text.

Required behavior:
- Treat encryption as mandatory for PII.
- If the PII value is a `String`, apply `TRIM` before encryption and keep case sensitivity.
- Require a job parameter containing the AWS Secrets Manager ARN used to retrieve the encryption key.
- Retrieve the key from AWS Secrets Manager before encryption; do not hardcode keys in code, config, or examples.
- Do not propose plain-text storage for PII fields.
- If the user asks to keep PII unencrypted, explicitly warn that this violates the default rule.

AWS secret rule:
- The secret identifier must arrive through a job parameter as an AWS Secrets Manager ARN.
- If the ARN parameter is missing, ask for it before finalizing the encryption flow.

Scala Spark guidance:
- Reuse the project encryption primitive when one already exists.
- If the field is textual, follow the same semantic rule defined for encrypted strings.
- Keep the secret retrieval step explicit in architecture, code examples, or pseudocode.

### `Date`

Rule:
- The transformation must be based on the declared input pattern.

Intent:
- Date parsing is format-dependent and should not be guessed.

Required behavior:
- If the input format is known, use it explicitly in the transformation.
- If the input format is not provided, ask for it.
- Do not infer ambiguous formats such as `dd/MM/yyyy` versus `MM/dd/yyyy` without confirmation.

Scala Spark guidance:
- Prefer `to_date(col("field"), "pattern")`.
- If normalization is needed before parsing, perform only safe preprocessing that does not alter date meaning.

Default example:

```scala
import org.apache.spark.sql.functions.{col, to_date}

df.withColumn("birth_date", to_date(col("birth_date"), "dd/MM/yyyy"))
```

### `Timestamp`

Rule:
- Do not allow transformation of the timestamp value.
- Preserve the original reference because of timezone risk.

Intent:
- Avoid semantic drift caused by timezone conversion, parsing assumptions, or formatting changes.

Required behavior:
- Keep the original timestamp field unchanged.
- Do not propose `to_timestamp`, timezone conversion, cast, reformatting, truncation, or string round-trip transformations by default.
- If the user requests timestamp manipulation, explicitly warn that this violates the default pattern and may alter timezone semantics.

Scala Spark guidance:
- Prefer passing the original column through unchanged.
- If a new column is needed for downstream compatibility, duplicate the original value without modifying it.

Default example:

```scala
import org.apache.spark.sql.functions.col

df.select(
	col("event_timestamp")
)
```

> For detailed timestamp normalization rules (timezone drift, "Z" suffix handling,
> `normalizeTimestampString` UDF), see the **timestamp-handling** skill.
> For applying all transformations via a single `select` instead of chained `withColumn`,
> see the **catalyst-optimization** skill.

## Review Rules

When reviewing Spark Scala code, flag the following as deviations from the standard:

- `String` columns without `trim` before standard normalization.
- PII fields stored or propagated without encryption.
- Encryption flows that do not retrieve the key from AWS Secrets Manager using the ARN parameter.
- Hardcoded encryption keys or examples that embed secrets directly in code.
- Encrypted string columns that apply `upper`, `lower`, or any case normalization before encryption.
- `Date` conversions that omit the input pattern.
- Any transformation on `Timestamp` columns that changes representation or timezone semantics.

## Response Expectations

When answering a transformation request, present the result in this order when applicable:

- `Column type`
- `Applied pattern`
- `Scala Spark transformation`
- `Reason`
- `Secret source` when encryption applies
- `Open question` if the date input format is missing

## Guardrails

- Do not generalize one column rule to all fields without checking the data type and business role.
- Do not leave PII unencrypted.
- Do not hardcode encryption keys.
- Do not omit the AWS Secrets Manager ARN parameter when encryption is required.
- Do not uppercase encrypted inputs.
- Do not guess date patterns.
- Do not alter timestamps by default.
- Preserve existing project conventions if the codebase already uses helper functions around Spark SQL functions, but keep the same semantic rules defined here.
