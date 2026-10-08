---
name: nested-field-extraction
description: "Use when extracting sub-fields from positional/fixed-width columns in Spark — substring extraction driven by NestedFieldSpec (1-based positions) and, for marker-delimited blocks, regex UDFs. Generic mechanism; ISO 8583 / BIT fields are one applied example (authorization tables only)."
---

# Nested / Positional Field Extraction

Use this skill whenever a single source column packs **multiple sub-fields at fixed positions** (fixed-width / positional layouts) and you need to split it into typed columns.

## Purpose

This skill defines the **generic mechanism** for extracting sub-fields from a positional column:
- `NestedFieldSpec` declares each sub-field (parent column, 1-based start, length, target type),
- `DataFrameUtils.substringExtract` materializes them in one fold,
- for blocks identified by **markers** (not fixed offsets), small regex UDFs extract the value.

The mechanism is domain-agnostic. **ISO 8583 / BIT fields are just one applied example** and occur **only in the authorization tables**; other tables that need positional extraction will have their own domain references. Do not treat the ISO 8583 specifics below as a general rule.

## Required Behavior

### Fixed-position sub-fields — `NestedFieldSpec` + `substringExtract`

Declare each sub-field with **1-based** positions (as in the SDD):

```scala
final case class NestedFieldSpec(
  parentColumn:   String,          // coluna pai (stagingField) de onde extrair
  targetName:     String,          // coluna destino
  startPos:       Int,             // posicao inicial (1-based)
  length:         Int,             // tamanho do substring
  targetType:     DataType,
  comment:        String,
  transformation: Option[String] = None
)
```

Extraction is a fold of `withColumn(substring(...))`:

```scala
def substringExtract(df: DataFrame, nestedSpecs: Seq[NestedFieldSpec]): DataFrame =
  nestedSpecs.foldLeft(df) { case (currentDf, spec) =>
    currentDf.withColumn(spec.targetName, substring(col(spec.parentColumn), spec.startPos, spec.length))
  }
```

Typing/transforming the extracted columns is done afterwards in the single `.select()` transform step (the model exposes the nested specs' cast fields alongside `fields`). See the **catalyst-optimization** skill.

### Marker-delimited blocks — regex UDFs

When sub-fields are not at fixed offsets but inside a marked block, use a small regex UDF that returns `null` on no-match (never throws). Keep the regex and the length rules in one place.

## Applied Example (authorization only) — ISO 8583 / BIT

> Everything in this section is specific to the authorization tables. Skip it for other domains.

- Fixed-position BITs (e.g. BIT63 packs billing/shipping addresses in positions 1–547) → `NestedFieldSpec` + `substringExtract`.
- BIT48 carries marker-delimited blocks → regex UDFs in `RegexExtractors`:
  - `*PRDnnn<value>` → product code (`applyPrdRegex`); `nnn` is the value length.
  - `*VPSnnnF<NN...>` → installments (`applyVpsRegex`); length rule: `>=3` → 2 digits, `==2` → 1 digit, `==1` → null.

See `scripts/NestedFieldSpec.scala` and `scripts/RegexExtractors.scala` (mirror production 1:1).

## Review Rules

When reviewing positional extraction code, flag the following as deviations:

- 0-based `startPos` (Spark `substring` and the SDD are **1-based**).
- Extraction logic hardcoded inline instead of declared as `NestedFieldSpec` on the model.
- Regex UDFs that throw instead of returning `null` on no-match / null input.
- Treating a marker-delimited block as fixed-offset (or vice-versa).
- Domain-specific BIT rules presented as general extraction rules.

## Guardrails

- Do not assume offsets — positions come from the source spec/SDD and are 1-based.
- Do not push typing into `substringExtract`; extract as string, cast in the single `.select()`.
- Keep regex patterns and their length rules colocated and null-safe.
- For the SDD section that enumerates nested fields, see the **sdd-specification** skill (section "Campos Aninhados").
