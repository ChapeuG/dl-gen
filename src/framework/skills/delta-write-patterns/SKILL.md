---
name: delta-write-patterns
description: "Use when implementing Delta Lake write operations including initial overwrite, incremental merge (upsert), batch deduplication, file sizing, and symlink manifest generation for Athena integration. Applies canonical write patterns for Delta tables in Spark."
---

# Delta Write Patterns

Use this skill whenever the task involves writing data to Delta Lake tables in Spark, including initial loads, incremental merges, and deduplication strategies.

## Purpose

This skill defines the canonical patterns for Delta table persistence: choosing between overwrite and merge, deduplicating before write, sizing output files, and generating manifests for Athena/Glue integration.

## Required Behavior

When implementing Delta writes in Spark Scala:

1. Detect whether the target path already contains a Delta table using `DeltaTable.isDeltaTable(path)`.
2. Use overwrite mode for first-time writes and merge mode for incremental loads.
3. Always deduplicate the source DataFrame before merge to avoid processing duplicate records, keeping the **most recent** record per merge key deterministically (`Window` + `row_number()`).
4. Use null-safe comparison (`<=>`) in merge conditions to handle NULL keys correctly.
5. On `whenMatched`, update every column **except `dh_criacao_registro`** (the creation timestamp is set once and never overwritten).
6. Generate the symlink format manifest after every write for Athena compatibility.
7. Configure Delta optimization settings (`optimizeWrite`, `autoMerge`, insert-only/repartition) before the write.

## Canonical Patterns

### Detecting Existing Table

```scala
val isDelta = DeltaTable.isDeltaTable(outputPath)
```

Use this check to decide between initial overwrite and incremental merge.

### Enable optimizeWrite (both paths)

```scala
// Adaptive file sizing for overwrite AND merge — avoids small files without OOM risk on large partitions
spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "true")
```

Set this before deciding the write mode; it applies to both overwrite and merge.

### Initial Overwrite (First Load)

```scala
val nrRows: Long = (128 * 1024 * 1024) / avgRowSize

df.write
  .mode(SaveMode.Overwrite)
  .format("delta")
  .option("delta.autoOptimize.optimizeWrite", "true")
  .option("maxRecordsPerFile", nrRows)
  .partitionBy(partitions: _*)
  .save(outputPath)
```

`maxRecordsPerFile` targets ~128MB per file. Calculate `nrRows` as `128MB / average_row_size_in_bytes`.

### Incremental Merge (Upsert)

```scala
// Optimization configs
spark.conf.set("spark.databricks.delta.merge.optimizeInsertOnlyMerge.enabled", "true")
spark.conf.set("spark.databricks.delta.merge.repartitionBeforeWrite.enabled", "true")
spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")

val conditions = mergeConditions
  .map { case (src, tgt) => s"s.$src <=> t.$tgt" }
  .mkString(" and ")

// Update every column EXCEPT dh_criacao_registro — the creation timestamp is preserved
val updateAssignments: Map[String, Column] =
  df.columns
    .filterNot(_ == "dh_criacao_registro")
    .map(c => c -> col(s"s.$c"))
    .toMap

DeltaTable.forPath(outputPath).alias("t")
  .merge(df.alias("s"), conditions)
  .whenMatched().update(updateAssignments)
  .whenNotMatched().insertAll()
  .execute()
```

Key points:
- `<=>` is the null-safe equality operator. Use it instead of `=` for merge conditions to correctly handle NULL keys.
- `optimizeInsertOnlyMerge`: skips rewriting files that have no matches, improving performance when most records are inserts.
- `repartitionBeforeWrite`: reduces the number of small files created by merge.
- `schema.autoMerge`: auto-evolves the target schema when the source adds compatible columns.
- **`update(updateAssignments)` instead of `updateAll()`**: `dh_criacao_registro` is excluded from the update set so the original creation timestamp is never overwritten on re-processing. Only `dh_atualizacao_registro` (and the payload) advances. See the **processing-timestamp** skill for how these timestamps are produced.

### Deduplication Before Merge

```scala
val w = Window.partitionBy(mergeKeys.map(col): _*).orderBy(col(timestampColumn).desc)
val deduped = df
  .withColumn("__rn", row_number().over(w))
  .filter(col("__rn") === 1)
  .drop("__rn")
```

Use `Window` + `row_number()` and keep row `__rn === 1` per merge key. This is **deterministic**: it guarantees the record with the greatest `timestampColumn` per key survives. The `orderBy(...).dropDuplicates(mergeKeys)` alternative saves one shuffle but is **not** deterministic — `dropDuplicates` re-partitions by the keys and discards the global ordering, keeping an arbitrary record per group. Correctness wins over the saved shuffle.

### Symlink Manifest for Athena

```scala
DeltaTable.forPath(outputPath).generate("symlink_format_manifest")
```

Always generate after write. Athena reads Delta tables through the `_symlink_format_manifest/` directory.

### File Sizing Formula

```
maxRecordsPerFile = targetFileSizeBytes / averageRowSizeBytes
```

- Target file size: 128MB (`128 * 1024 * 1024` bytes)
- Average row size: estimate from schema (e.g., 340 bytes for authorization transactions)
- Adjust based on compression ratio if using snappy/zstd

## Review Rules

When reviewing Delta write code, flag the following as deviations:

- Missing `DeltaTable.isDeltaTable` check before deciding write mode.
- Using `=` instead of `<=>` in merge conditions (NULL keys will not match).
- Missing deduplication before merge (duplicate source records cause incorrect merge results).
- Non-deterministic dedup (`dropDuplicates` on ordered DataFrame) when the most-recent record must be kept — use `Window` + `row_number()`.
- Using `whenMatched().updateAll()` when `dh_criacao_registro` must be preserved (should use `update(updateAssignments)` excluding it).
- Missing manifest generation after write.
- Missing `maxRecordsPerFile` or partition distribution on initial write (leads to many small files).
- Hardcoded merge conditions instead of deriving from model/structure.
- Missing Delta optimization configs (`optimizeWrite`, `autoMerge`, insert-only/repartition) before merge.

## Response Expectations

When answering about Delta writes, present in this order when applicable:

- `Write mode` (overwrite or merge)
- `Merge condition` with null-safe operator
- `Deduplication strategy` (deterministic `Window` + `row_number()`)
- `Update set` (all columns except `dh_criacao_registro`)
- `File sizing` calculation
- `Manifest generation`
- `Open question` if merge keys or average row size are unknown

## Guardrails

- Do not skip deduplication before merge.
- Do not rely on `dropDuplicates` when the most-recent record must win; use deterministic `Window` + `row_number()`.
- Do not use `=` in merge conditions; always use `<=>` for null safety.
- Do not overwrite `dh_criacao_registro` on `whenMatched`; exclude it from the update assignments.
- Do not forget manifest generation after write operations.
- Do not hardcode file sizes without considering average row size.
- Do not skip `DeltaTable.isDeltaTable` check; always handle both first-load and incremental scenarios.
- For persist/unpersist strategy around merge operations, see the **dataframe-persist-strategy** skill.
- For how the run timestamp feeds `dh_criacao_registro`/`dh_atualizacao_registro` and the partition column, see the **processing-timestamp** skill.
