---
name: processor-orchestration
description: "Use when writing or reviewing a table processor end-to-end — the canonical step sequence (read → rename → substring → single-select transform → derive partition → enrich → fact-join → dedup → traceability → persist → save → Hive → partitions) and when to split a complex table into Processor + Pipeline + JoinSpec. The narrative index that ties the other skills together."
---

# Processor Orchestration

Use this skill whenever the task is to author or review a full table **processor** — the top-level flow that reads a source, transforms it, and lands it as a Delta + Hive table.

## Purpose

This skill defines the **canonical processor flow** and the split between orchestration and pure transformations. It is the narrative index: each step points to the skill that owns its details.

## Canonical Step Sequence

Every processor follows the same skeleton (a step is skipped only when it does not apply):

1. **Resolve params** — mandatory `data_source` / `output_uri`, optional `database` (model default) and `s3_base_path` (derived from `output_uri`). → **job-parameters**
2. **Resolve the run timestamp once at the driver** — `runInstant`/`runTimestamp`/`runDateYyyymmdd`. → **processing-timestamp**
3. **Read** the source (positional CSV, JSON with a `StringType` schema, …).
4. **Rename** raw → staging (`DataFrameUtils.renameColumns` from `model.rawToStagingMap`).
5. **Substring-extract** nested/positional sub-fields (`DataFrameUtils.substringExtract`), when the model declares them. → **nested-field-extraction**
6. **Transform in a single `.select()`** — build `Map[targetName -> TransformColumn(f)]` and project once. → **catalyst-optimization** (rules → **data-transformation-patterns**, **timestamp-handling**)
7. **Derive the partition column(s)** — either from a data column (`date_format(...)`) or `lit(runDateYyyymmdd)` for the update partition. → **processing-timestamp**
8. **Enrich** with dimension lookups (`ApplyEnrichment.applyAll`). → **enrichment-joins**
9. **Fact-to-fact join** with complement tables (`FactRightJoin`), interleaved with their enrichments. → **fact-to-fact-joins**
10. **Deduplicate** deterministically (`DeltaWritePattern.dedup`, keep most-recent per merge key). → **delta-write-patterns**
11. **Add traceability** (`addTraceabilityFields(df, runTimestamp)`). → **processing-timestamp**
12. **Persist + materialize** before the merge (`persist(...)`; `.count` on the heavy consolidated table). → **dataframe-persist-strategy**
13. **Save** to Delta (merge or first-load overwrite; manifest generated inside). → **delta-write-patterns**
14. **Hive** create + evolve schema; **register partitions** in batches of 100. → **hive-table-management**
15. **`unpersist()` in `finally`.**

Errors bubbling out of the flow are classified and (optionally) reported to SQS by `Main`. → **error-handler**

## Simple vs Complex Tables

### Simple (single source, no fact joins)

Everything lives in one `Processor` object. It computes only `runTimestamp` (the partition is derived from a data column), runs steps 3–15 inline, and persists with `MEMORY_AND_DISK`. Example shape (simple table):

```scala
val runTimestamp = Timestamp.from(Instant.now())
val renamedDf    = DataFrameUtils.renameColumns(rawDf, model.rawToStagingMap)
val transformedDf = renamedDf.select(/* single-select via TransformColumn */)
val partitionedDf = transformedDf.withColumn("dt_..._particao", date_format(...))
val enrichedDf    = ApplyEnrichment.applyAll(partitionedDf, model.enrichments, s3BasePath)
val dedupDf       = DeltaWritePattern.dedup(enrichedDf, model.mergeKeys, model.timestampField)
val traceDf       = DataFrameUtils.addTraceabilityFields(dedupDf, runTimestamp)
traceDf.persist(StorageLevel.MEMORY_AND_DISK)
try { DeltaWritePattern.save(...); HiveTableManager.createTable/evolveSchema/registerPartitions(...) }
finally { traceDf.unpersist() }
```

### Complex (fact joins, many enrichments)

Split into three objects, keeping the `Processor` focused on orchestration:

- **`Processor`** — params, run timestamp, path resolution, `persist`/`.count`, `save`, Hive, `unpersist`.
- **`Pipeline`** — pure transformations as named stages: `readRaw → toStaging → castAndTransform → enrichAndJoin → finalizeOutput`. No I/O for write/Hive.
- **`JoinSpec`** — join key/rename/drop constants for the fact joins. → **fact-to-fact-joins**

The consolidated `pedido_consolidado` uses `MEMORY_AND_DISK_SER` and forces materialization with `traceDf.count` before the merge, then derives the pruning `partitionDate` from `--processing_date` or the run date.

## Review Rules

When reviewing a processor, flag the following as deviations:

- Steps out of order (e.g. dedup before enrichment when the enrichment can change merge-key columns; traceability before dedup).
- Transformations implemented as chained `withColumn` instead of a single `.select()` (see catalyst-optimization; partition-deriving `withColumn`s at the end are the accepted exception).
- I/O (write/Hive) implemented inside `Pipeline` stages instead of the `Processor`.
- Join key/rename/drop constants inlined in the processor instead of a `JoinSpec`.
- Missing `persist`/`unpersist` around the merge, or missing `.count` on the heavy path.
- Run timestamp recomputed per stage instead of threaded from step 2.
- A complex table with fact joins collapsed into one monolithic `Processor` (no `Pipeline`/`JoinSpec`).

## Guardrails

- Do not centralize multiple tables in one processor (one processor per table). → **project-structure**
- Do not move write/Hive I/O into pure transformation stages.
- Do not reorder steps in a way that changes merge semantics (dedup keeps the most-recent per key; traceability and partition columns are set before persist/save).
- Preserve the run-timestamp-once discipline throughout the flow.
- This skill is the map; defer implementation details to the linked skills.
