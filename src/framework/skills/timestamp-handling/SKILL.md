---
name: timestamp-handling
description: "Use when implementing or reviewing timestamp parsing and normalization in Spark, especially to avoid timezone drift caused by UTC 'Z' suffix, session timezone interaction, or format inconsistencies. Complements the data-transformation-patterns skill with detailed timestamp-specific rules."
---

# Timestamp Handling in Spark

Use this skill whenever the task involves parsing, normalizing, or preserving timestamp values in Spark DataFrames.

## Purpose

This skill defines rules for handling timestamps safely in Spark, with special focus on timezone drift prevention. It complements the **data-transformation-patterns** skill, which states the general rule "do not transform timestamps." This skill details the specific scenarios where normalization IS required and how to do it safely.

> Scope note: this skill is about parsing **source** string timestamps into `TimestampType`. For the **run/processing timestamp** the job assigns to its own records (driver-side `Instant.now`, update partition column, merge pruning), see the **processing-timestamp** skill instead.

## Required Behavior

When working with timestamps in Spark Scala:

1. Preserve the original timezone reference. Do not apply timezone conversions unless explicitly requested.
2. Remove or neutralize the "Z" (UTC) suffix before calling `to_timestamp` when the session timezone is not UTC.
3. Use `normalizeTimestampString` UDF for raw string-to-timestamp conversion to handle format inconsistencies.
4. When a custom format is known, use `to_timestamp(col, format)` explicitly.
5. Never apply `TRIM + UPPER` to timestamp strings — this can alter or destroy temporal information.

## The "Z" Suffix Problem

### Root cause

Spark's `to_timestamp` interprets timestamps with "Z" suffix as UTC. If the Spark session timezone is set to a local timezone (e.g., `America/Sao_Paulo`, UTC-3), the parsed timestamp is automatically converted:

```
Input:  "2024-01-15T10:30:00Z"
Session timezone: America/Sao_Paulo (UTC-3)
Result: 2024-01-15 07:30:00  (3 hours subtracted)
```

This is technically correct per ISO 8601, but causes data drift when the source system emitted the timestamp in local time and incorrectly appended "Z".

### Solution

The `normalizeTimestampString` UDF strips format issues before `to_timestamp` is applied:

```scala
private val normalizeTimestampString: UserDefinedFunction = udf { (value: String) =>
  try {
    if (value == null) null
    else {
      val trimmed = value.replace(" ", "")
      if (trimmed.length >= 18) {
        val upper = trimmed.toUpperCase
        val withT = if (upper.indexOf("T") == -1)
          upper.substring(0, 10) + "T" + upper.substring(10)
        else upper
        withT.replace("/", "-")
      } else value
    }
  } catch {
    case _: Exception => value
  }
}
```

See `scripts/NormalizeTimestamp.scala` for the full implementation.

### What the UDF does

1. **Removes spaces**: Handles inconsistent spacing in raw data.
2. **Ensures "T" separator**: If the timestamp lacks the ISO 8601 "T" between date and time, inserts it.
3. **Normalizes "/" to "-"**: Converts `2024/01/15` to `2024-01-15`.
4. **Does NOT remove "Z"**: The UDF normalizes format but does not strip timezone indicators. If "Z" removal is needed, handle it before the UDF.

### Application in transformColumn

```scala
case (TimestampType, Some("default")) => to_timestamp(NormalizeTimestamp.normalizeTimestampString(col(f.targetName)))
case (TimestampType, Some("format"))  => to_timestamp(NormalizeTimestamp.normalizeTimestampString(col(f.targetName)), f.sourceFormat.get)
```

## When to Use Custom Format

If the source timestamp format is known and non-standard:

```scala
// Source: "15/01/2024 10:30:00"
to_timestamp(col("field"), "dd/MM/yyyy HH:mm:ss")
```

Always declare the format explicitly. Do not rely on Spark's default parsing which assumes ISO 8601.

## Relationship with data-transformation-patterns

The **data-transformation-patterns** skill states:
> "Do not allow transformation of the timestamp value. Preserve the original reference because of timezone risk."

This skill **complements** that rule:
- The general rule remains: do not apply arbitrary transformations.
- When raw data requires parsing from string to TimestampType, use `normalizeTimestampString` + `to_timestamp` as the safe path.
- The UDF normalizes format without altering the temporal value.

## Review Rules

When reviewing timestamp handling code, flag the following as deviations:

- Calling `to_timestamp` on strings that may contain "Z" suffix without considering session timezone.
- Applying `TRIM + UPPER` to timestamp strings (UPPER converts "am/pm" markers, TRIM is safe but unnecessary when using the UDF).
- Missing format parameter when the source format is known and non-ISO.
- Using `cast(TimestampType)` instead of `to_timestamp` (cast has weaker format handling).
- Timezone conversion functions (`from_utc_timestamp`, `to_utc_timestamp`) applied without explicit user request.
- Missing null check in timestamp parsing logic.

## Response Expectations

When answering about timestamp handling, present in this order when applicable:

- `Source format` (ISO 8601, custom, unknown)
- `Timezone risk` (Z suffix present, session timezone mismatch)
- `Normalization applied` (UDF, custom format, none)
- `Spark expression` used
- `Open question` if source format or timezone context is unknown

## Guardrails

- Do not ignore the "Z" suffix problem when session timezone is not UTC.
- Do not apply string transformations (UPPER, LOWER, TRIM) to timestamps beyond what the normalization UDF does.
- Do not use `cast(TimestampType)` as a substitute for `to_timestamp` with format.
- Do not assume all timestamps in the same pipeline share the same format.
- Do not apply timezone conversion unless the user explicitly confirms the source and target timezones.
- Preserve the `normalizeTimestampString` UDF as the standard preprocessing step for raw timestamp strings.
