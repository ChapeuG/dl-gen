---
name: enrichment-joins
description: "Use when implementing joins between a main DataFrame and small dimension/lookup tables (country, currency, MCC, BIT codes). Applies broadcast join patterns, sequential aliasing, and the Enrichment trait contract for enrichment pipelines in Spark."
---

# Enrichment Joins with Broadcast

Use this skill whenever the task involves joining a main DataFrame against one or more small dimension or lookup tables in Spark.

## Purpose

This skill defines the canonical pattern for enrichment joins: reading a small Delta lookup table, broadcasting it, joining with the main DataFrame, and managing column aliasing to avoid ambiguity across multiple sequential joins.

## Required Behavior

When implementing enrichment joins in Spark Scala:

1. Use `broadcast()` for all dimension/lookup tables that are known to be small (< 10MB): country, currency, MCC, BIT authorization codes, and similar reference data.
2. Apply early projection: select only the columns needed for the join condition and the enrichment result before broadcasting.
3. Use sequential aliasing with prefix `delta{seq}_` for join keys to prevent column ambiguity when chaining multiple joins.
4. Increment the sequence counter only for active enrichments (`isActive == true`).
5. Do not use `broadcast()` for RIGHT JOINs where the lookup-side volume is uncertain (e.g., tables filtered by daily partition whose size varies).
6. Follow the `Enrichment` trait contract for defining each join.

## Enrichment Trait Contract

Each enrichment join is defined by the `Enrichment` trait:

```scala
trait Enrichment {
  val team: String           // S3 path segment: team name
  val dataset: String        // S3 path segment: dataset name
  val table: String          // S3 path segment: table name
  val lookupColumnList: List[String]              // Columns to retrieve from lookup
  val lookupColumnAliasList: Map[String, String]  // Column renames (original -> alias)
  val lookupJoinConditions: Map[String, String]   // lookup_col -> df_col
  val lookupFixedConditions: Map[String, String] = Map.empty       // lookup_col -> literal value
  val lookupConditionalConditions: Map[String, Column] = Map.empty // lookup_col -> expr derived from the fact
  val lookupJoinType: String // "left", "inner", "right", etc.
  val isActive: Boolean      // Skip join if false
}
```

### Three kinds of join condition

The join condition is the `and` of up to three groups (all keys are aliased with the `delta{seq}_` prefix on the lookup side before comparison):

- **`lookupJoinConditions`** (`lookup_col -> df_col`): the normal case — compare a lookup column to a column of the fact DataFrame.
- **`lookupFixedConditions`** (`lookup_col -> literal`): pin a lookup column to a constant when the fact does not carry that column. Example: the partner feed always uses `cd_canal = "7"`.
- **`lookupConditionalConditions`** (`lookup_col -> Column`): compare a lookup column against an expression derived from other fact columns. The expression references fact columns by simple name (e.g. `col("cd_canal")`) and is resolved in the join context. Example (BIT39): `cd_responsavel_mensagem_transacao` = `when(col("cd_canal") === 7, 1).when(col("cd_canal") === 9, 4)`.

The early projection selects `lookupColumnList ++` the keys of **all three** condition maps.

## Canonical Pattern

### Helper function `applyEnrichment`

See `scripts/ApplyEnrichment.scala` for the full implementation.

Flow:

1. Build the S3 path from `(team, dataset, table)`.
2. Select only required columns: `lookupColumnList ++ lookupJoinConditions.keys ++ lookupFixedConditions.keys ++ lookupConditionalConditions.keys`.
3. Wrap with `broadcast()`.
4. Rename result columns using `lookupColumnAliasList`.
5. Rename all join keys (normal + fixed + conditional) with `delta{seq}_` prefix to avoid ambiguity.
6. Build the join condition as the `and` of the normal (`=== df_col`), fixed (`=== lit(value)`), and conditional (`=== expr`) groups.
7. Execute the join with the specified `lookupJoinType`.
8. Rename or drop temporary key columns after the join.

### Application loop

```scala
var enrichedDf = df
var seq = 1
joinSeq.foreach { enrichment =>
  enrichedDf = applyEnrichment(enrichedDf, enrichment, s3Path, seq)
  if (enrichment.isActive) seq += 1
}
```

## When NOT to Use Broadcast

- **RIGHT JOINs with partition-filtered tables**: When the lookup side is filtered by a daily partition (`dt_particao = 'YYYYMMDD'`), the post-filter volume depends on the batch. Let Spark choose the optimal plan. This fact-to-fact case is a separate pattern — see the **fact-to-fact-joins** skill (`FactRightJoin`).
- **Large dimension tables** (> 10MB): If the lookup table exceeds the broadcast threshold, a sort-merge join with shuffle may be more efficient.
- **Skewed join keys**: Broadcast does not help with data skew on the main DataFrame side.

## Review Rules

When reviewing enrichment join code, flag the following as deviations:

- Dimension table joins without `broadcast()` hint for known small tables.
- Missing early projection (`select`) before broadcasting a lookup table.
- Missing sequential alias prefix when multiple joins are chained.
- Using `broadcast()` on RIGHT JOIN with variable-size lookup tables.
- Hardcoded S3 paths instead of constructing from `(team, dataset, table)`.
- Inactive enrichments (`isActive == false`) still incrementing the sequence counter.

## Response Expectations

When answering about enrichment joins, present in this order when applicable:

- `Join type` (left, inner, right)
- `Broadcast decision` (yes/no with reason)
- `Lookup columns` selected
- `Join condition` with alias references
- `Column management` (renames, drops)
- `Open question` if enrichment trait fields are unclear

## Guardrails

- Do not broadcast tables whose size is unknown or variable.
- Do not skip early projection before broadcasting.
- Do not use the same alias prefix for different joins in the same pipeline.
- Do not alter the `===` join operator semantics (it is not null-safe by design in enrichment joins).
- Preserve existing `Enrichment` trait implementations when they are already defined in the model.
