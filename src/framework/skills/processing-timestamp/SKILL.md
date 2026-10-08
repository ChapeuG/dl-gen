---
name: processing-timestamp
description: "Use when a processor needs a single run timestamp resolved at the driver (Instant.now) to stamp records, derive the update partition column, and prune complement tables in fact-to-fact joins — the pattern that makes the Delta merge deterministic and partition-prunable. Distinct from timestamp-handling, which is about parsing source string timestamps."
---

# Processing (Run) Timestamp

Use this skill whenever a Spark processor must produce a consistent run timestamp / processing date and use it for record traceability, the update partition column, and partition pruning of complement tables.

## Purpose

This skill defines the **run-timestamp** pattern: resolve the current instant **once, at the driver, at the start of the processor**, and reuse it as a literal throughout the job. This is the pattern that makes the Delta merge both **deterministic** and **partition-prunable**.

It is **distinct** from the **timestamp-handling** skill:
- **timestamp-handling** — parsing raw *source* strings into `TimestampType` (the "Z" suffix / format normalization problem).
- **processing-timestamp** (this skill) — the *execution* stamp the job assigns to the records it writes.

## Required Behavior

At the very start of the processor (before any transformation):

1. Resolve the instant **once at the driver**:

```scala
import java.sql.Timestamp
import java.time.{Instant, ZoneOffset}
import java.time.format.DateTimeFormatter

// Resolvido uma vez no driver — vira literal no plano, imune a re-otimizacao do Catalyst
val runInstant      = Instant.now()
val runTimestamp    = Timestamp.from(runInstant)
val runDateYyyymmdd = runInstant.atZone(ZoneOffset.UTC).toLocalDate
                        .format(DateTimeFormatter.ofPattern("yyyyMMdd"))
```

2. Never call `current_timestamp()` / `current_date()` inside transformations for these values — those are evaluated per-task and are **not** stable across the plan.
3. Pass `runTimestamp` / `runDateYyyymmdd` down into the pipeline stages; wrap them with `lit(...)` when they become columns.

## Why Resolve Once at the Driver

- **Determinism.** Every row written in the run gets the *same* creation/update stamp and the *same* update-partition value. Deduplication and merge become reproducible; there is no per-task clock skew.
- **Catalyst immunity.** A driver-side `val` wrapped in `lit(...)` is a constant in the logical plan. It is not re-evaluated, reordered, or recomputed by Catalyst, and it enables constant-folding and partition elimination.
- **Partition pruning.** Because the update-partition value is a literal, the Delta MERGE and downstream reads can prune to a single partition.

## The Three Uses

### 1. Update partition column (`lit`)

```scala
transformed.withColumn("dt_atualizacao_registro_particao", lit(runDateYyyymmdd))
```

All rows land in one partition (the run date). This is the L2 partition that lets the MERGE and later reads eliminate every other partition.

### 2. Partition pruning of complement tables (fact-to-fact join)

The processing date drives the partition filter applied to complement tables **before** the join. Prefer an explicit `--processing_date` when provided, else fall back to the run date:

```scala
val partitionDate: Column = params.get("processing_date") match {
  case Some(d) => lit(d)
  case None    => lit(runDateYyyymmdd)
}
// ...
.filter(col("dt_atualizacao_registro_particao") === partitionDate)   // pruning inside FactRightJoin
```

See the **fact-to-fact-joins** skill for the full join.

### 3. Traceability fields (`lit(runTimestamp)`)

```scala
def addTraceabilityFields(df: DataFrame, runTimestamp: Timestamp): DataFrame = {
  val ts = lit(runTimestamp)
  df.withColumn("dh_criacao_registro", ts)
    .withColumn("dh_atualizacao_registro", ts)
}
```

On the Delta MERGE, `dh_criacao_registro` is **excluded** from the update set so it keeps the value from the first insert; only `dh_atualizacao_registro` advances on re-processing. See the **delta-write-patterns** skill.

## Relationship with `--processing_date`

`--processing_date` (`yyyyMMdd`) is a **project-specific** parameter (authorization pipeline) that overrides only the *pruning* date used against complement tables; when absent it defaults to `runDateYyyymmdd`. It does not change the traceability stamp. See the **job-parameters** skill (project-specific parameters).

## Review Rules

When reviewing run-timestamp handling, flag the following as deviations:

- Calling `current_timestamp()` / `current_date()` inside transformations for the record stamp or partition value (non-deterministic across tasks).
- Resolving `Instant.now()` more than once, or inside a stage/UDF, so different rows get different stamps.
- Deriving `dt_atualizacao_registro_particao` from a per-row expression instead of `lit(runDateYyyymmdd)`.
- Using a mix of UTC and local time between the timestamp and the derived date (here the date is derived in `ZoneOffset.UTC`).
- Updating `dh_criacao_registro` on `whenMatched` (it must be preserved — see delta-write-patterns).

## Guardrails

- Do not recompute the run timestamp downstream; compute once at the driver and thread it through.
- Do not confuse this with source timestamp parsing — see **timestamp-handling**.
- Do not drop the `lit(...)` wrapper; a bare Scala value cannot be used as a Column.
- Preserve the UTC derivation of `runDateYyyymmdd` unless the user explicitly requests a different zone.
