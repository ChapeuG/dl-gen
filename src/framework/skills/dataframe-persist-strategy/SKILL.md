---
name: dataframe-persist-strategy
description: "Use when deciding whether, where, and how to persist (cache) Spark DataFrames. Covers the persist/unpersist pattern for Delta MERGE operations, StorageLevel selection, placement in the pipeline (post-dedup vs pre-dedup), and the try/finally cleanup pattern."
---

# DataFrame Persist Strategy

Use this skill whenever the task involves deciding whether to persist (cache) a Spark DataFrame, choosing the right StorageLevel, or managing the persist/unpersist lifecycle.

## Purpose

This skill defines when and how to use `persist()` and `unpersist()` in Spark pipelines, with specific focus on Delta MERGE operations where the source DataFrame is materialized multiple times.

## Required Behavior

When working with DataFrame persistence in Spark:

1. Only persist DataFrames that are materialized more than once by downstream operations.
2. Persist the **final** DataFrame (post-dedup, post-traceability) **immediately before the merge**, not intermediate stages.
3. Force materialization right after `persist` with an action (`.count`) so the cache is populated before the MERGE reads it twice.
4. Choose the `StorageLevel` by pipeline weight: `MEMORY_AND_DISK_SER` for heavy, wide pipelines (many joins — e.g. the consolidated `pedido_consolidado`); `MEMORY_AND_DISK` for lighter single-source processors (e.g. a simple single-table processor).
5. Always wrap persistent DataFrames in `try/finally` to guarantee `unpersist()`.
6. Do not persist DataFrames used only once.

## When to Persist

### Delta MERGE (Primary Use Case)

Delta Lake's MERGE operation materializes the source DataFrame **twice** internally:
1. Once to identify matched rows (for `whenMatched().update(...)`).
2. Once to identify non-matched rows (for `whenNotMatched().insertAll()`).

Without persist, the entire transformation chain (reads, joins, dedup, traceability) is recomputed from scratch for each materialization.

```
Pipeline without persist:
  Read -> 60 joins -> dedup -> traceability -> MERGE matched (full recompute)
  Read -> 60 joins -> dedup -> traceability -> MERGE not-matched (full recompute)

Pipeline with persist:
  Read -> 60 joins -> dedup -> traceability -> persist -> MERGE matched (from cache)
                                                        -> MERGE not-matched (from cache)
```

### Other Multi-Materialization Scenarios

- DataFrame used in both a write operation AND a subsequent query (e.g., partition value collection).
- DataFrame joined with itself (self-join).
- DataFrame used in multiple output writes (e.g., writing to Delta + sending to SQS).

## Where in the Pipeline to Persist

**Correct:** Persist the smallest possible DataFrame that captures all needed computation — after dedup + traceability, right before the write.

```scala
// dedup (deterministic) + traceability FIRST, then persist — caches fewer, final rows
val dedup   = DeltaWritePattern.dedup(enriched, model.mergeKeys, model.timestampField)
val traceDf = DataFrameUtils.addTraceabilityFields(dedup, runTimestamp)
traceDf.persist(StorageLevel.MEMORY_AND_DISK_SER)
```

**Anti-pattern:** Persisting before dedup caches duplicate rows that will be discarded.

```scala
// Persists ALL rows including duplicates — wastes memory
df.persist(StorageLevel.MEMORY_AND_DISK)
val deduped = DeltaWritePattern.dedup(df, mergeKeys, timestampField)
```

## Canonical Pattern

This is the real shape used by the consolidated processor: persist the final `traceDf`, force materialization with `.count`, then write and register partitions inside `try`, unpersist in `finally`.

```scala
val traceDf = PedidoConsolidadoPipeline.finalizeOutput(enriched, runTimestamp)

traceDf.persist(StorageLevel.MEMORY_AND_DISK_SER)
traceDf.count  // materializes the cache before the MERGE reads the source twice

try {
  // Delta MERGE + first-load overwrite (materializes source 2x on merge)
  val mergeConditions = model.mergeKeys.map(k => k -> k).toMap
  DeltaWritePattern.save(spark, traceDf, outputPath, mergeConditions, model.partitionColumns)

  // Subsequent operations that reuse the same cached DataFrame
  HiveTableManager.createTable(spark, fullTableName, traceDf.schema, model.partitionColumns, outputPath, ...)
  HiveTableManager.registerPartitions(spark, fullTableName, traceDf, model.partitionColumns)
} finally {
  traceDf.unpersist()
}
```

The lighter, single-source processors follow the same shape with `StorageLevel.MEMORY_AND_DISK`.

## StorageLevel Selection

| Level | When to use |
|---|---|
| `MEMORY_AND_DISK` | Lighter single-source processors. Data spills to disk if it exceeds executor memory. Avoids recomputation. |
| `MEMORY_AND_DISK_SER` | Heavy, wide pipelines (many joins, large rows — e.g. the consolidated `pedido_consolidado`). Smaller memory footprint, higher CPU; the safer default under memory pressure. |
| `MEMORY_ONLY` | When you are certain the data fits in memory and want to avoid disk I/O overhead. |
| `DISK_ONLY` | When memory is constrained and the recomputation cost is very high. Rare. |

Rule of thumb in this project: `MEMORY_AND_DISK_SER` for the consolidated table, `MEMORY_AND_DISK` for single-source processors. Both spill to disk, so neither risks OOM from the cache itself.

## When NOT to Persist

- **Single-use DataFrames:** Read once, write once. Persist adds overhead (serialization, cache management) without benefit.
- **Small DataFrames:** If the DataFrame fits in a single partition and the transformation is trivial, recomputation is cheaper than cache management.
- **Before dedup:** Caching duplicates wastes memory.
- **Inside loops:** Persisting inside a `foreach` loop without unpersisting accumulates cached data.

## Review Rules

When reviewing persist/unpersist code, flag the following as deviations:

- Missing `persist` before Delta MERGE with complex upstream pipeline.
- Missing materialization action (`.count`) right after `persist`, so the cache is only built lazily during the first MERGE pass.
- Missing `unpersist` after the persisted DataFrame is no longer needed.
- Missing `try/finally` around persist/unpersist lifecycle.
- Persisting before deduplication (caching more data than necessary).
- Using `MEMORY_ONLY` when the data size is uncertain (risk of OOM or silent eviction).
- Persisting single-use DataFrames (unnecessary overhead).

## Response Expectations

When answering about persist strategy, present in this order when applicable:

- `Materialization count` (how many times the DataFrame is consumed downstream)
- `Persist placement` (which stage in the pipeline)
- `StorageLevel` with justification
- `Cleanup pattern` (try/finally)
- `Open question` if downstream usage pattern is unclear

## Guardrails

- Do not persist without a clear multi-materialization justification.
- Do not forget `unpersist()` — use `try/finally` to guarantee cleanup.
- Do not persist before dedup — always deduplicate first.
- Do not use `MEMORY_ONLY` unless you have confirmed the data fits in executor memory.
- Do not persist inside loops without corresponding unpersist in each iteration.
- Do not skip the `.count` after `persist` when a MERGE follows — without it the cache is not populated before the double read.
- For Delta write patterns that trigger persist, see the **delta-write-patterns** skill.
- For where `persist` sits in the overall processor flow, see the **processor-orchestration** skill; for the run timestamp used in traceability, see **processing-timestamp**.
