---
name: catalyst-optimization
description: "Use when optimizing Spark DataFrame transformation pipelines for Catalyst query plan efficiency. Covers single-select pattern vs chained withColumn, pattern-matching transformation dispatch, early projection in joins, and removal of unnecessary mutable state abstractions."
---

# Catalyst Optimization Patterns

Use this skill whenever the task involves optimizing Spark DataFrame transformation pipelines for better Catalyst query plan generation.

## Purpose

This skill defines patterns that produce simpler, more efficient Catalyst logical plans by reducing the number of plan nodes, eliminating unnecessary abstractions, and applying projections early.

## Required Behavior

When writing or reviewing Spark transformation pipelines:

1. Prefer a single `.select()` over chained `.withColumn()` calls when transforming multiple columns.
2. Use pattern matching on `(targetType, transformation)` to dispatch column transformations (see `TransformColumn`).
3. Derive transformations directly from the field metadata (`Seq[FieldSpec]`); do not introduce mutable global registries.
4. Apply early projection (`select` only needed columns) before joins to reduce shuffle size.
5. Collect all field transformations into a `Map[String, Column]` and apply them in one pass.

## Canonical Patterns

### Single Select vs Chained withColumn

**Anti-pattern:** Each `withColumn` adds a new Project node to the Catalyst logical plan.

```scala
// 100 withColumn calls = 100 Project nodes in logical plan
var df = input
fields.foreach { f =>
  df = df.withColumn(f.name, transform(f))
}
```

**Correct pattern:** A single `select` produces 1 Project node regardless of column count.

```scala
val fieldTransformMap: Map[String, Column] =
  model.fields.map(f => f.targetName -> TransformColumn(f)).toMap

val transformed = df.select(
  df.columns.map { colName =>
    fieldTransformMap.getOrElse(colName, col(colName)).as(colName)
  }: _*
)
```

This reduces the logical plan from O(n) nodes to O(1), enabling better Catalyst optimization (predicate pushdown, column pruning).

### Pattern Matching for Transformation Dispatch

Instead of if/else chains or mutable registries, use pattern matching on the field metadata. In this project the dispatch lives in `TransformColumn` and matches on `(targetType, transformation)`, where `transformation: Option[String]` (`None` means "no transformation", `Some("default")`/`Some("format")` select the rule):

```scala
def apply(f: FieldSpec): Column = (f.targetType, f.transformation) match {
  case (_, None)                      => col(f.targetName)            // null no SDD — preserva
  case (StringType, Some("default"))  => trim(upper(col(f.targetName)))
  case (IntegerType, Some("default")) => col(f.targetName).cast(IntegerType)
  case (LongType, Some("default"))    => col(f.targetName).cast(LongType)
  case (dt, Some("default")) if dt.simpleString.contains("decimal") =>
    col(f.targetName).cast(f.targetType)
  case (DateType, Some("default"))    => to_date(col(f.targetName))
  case (DateType, Some("format"))     => to_date(col(f.targetName), f.sourceFormat.get)
  case (TimestampType, Some("default")) =>
    to_timestamp(NormalizeTimestamp.normalizeTimestampString(col(f.targetName)))
  case (TimestampType, Some("format"))  =>
    to_timestamp(NormalizeTimestamp.normalizeTimestampString(col(f.targetName)), f.sourceFormat.get)
  case (BooleanType, Some("default")) =>
    when(col(f.targetName).isin("s", "S", "true"), value = true)
      .when(col(f.targetName).isin("n", "N", "false"), value = false)
  case _ => col(f.targetName)
}
```

See `scripts/TransformColumn.scala` for the full implementation (mirrors production 1:1).

Benefits:
- Extensible: add new types by adding a case.
- No mutable state: pure function from `FieldSpec` metadata to a `Column` expression.
- Reads directly off the model's `Seq[FieldSpec]` — the same metadata used everywhere else.

### Deriving Transformations from Model Metadata (no mutable registries)

**Anti-pattern:** Global mutable state that registers transformations at runtime.

```scala
// Mutable global map populated at runtime — avoid this
object ModelUtils {
  var transformation: mutable.Map[String, (String, Column)] = mutable.Map()
}
```

**Correct pattern:** The model exposes `fields: Seq[FieldSpec]` (and, when applicable, `nestedCastFields`). Build the transform map straight from that metadata — no reflection, no registration step:

```scala
val allTransforms: Map[String, Column] =
  (model.fields.map(f => f.targetName -> TransformColumn(f)) ++
    model.nestedCastFields.map(f => f.targetName -> TransformColumn(f))).toMap
```

### Early Projection in Joins

Before joining with a lookup table, select only the columns needed:

```scala
val selectCols = (enrichment.lookupColumnList ++ enrichment.lookupJoinConditions.keys).distinct
val lookupDf = spark.read.format("delta").load(lookupPath)
  .select(selectCols.map(col): _*)  // Early projection
```

This reduces:
- Memory footprint of the broadcasted table.
- Shuffle size if broadcast is not used.
- Number of columns carried through subsequent operations.

## Review Rules

When reviewing Spark transformation code, flag the following as deviations:

- More than 5 consecutive `withColumn` calls that could be consolidated into a single `select` (partition-deriving `withColumn`s at the end of a stage are an accepted exception).
- Mutable global state used for transformation registration.
- Missing early projection before joins (selecting all columns when only a few are needed).
- If/else chains for type-based dispatch that could use `TransformColumn`-style pattern matching.
- Indirection layers that hide a simple `(targetType, transformation)` dispatch behind extra abstractions.

## Response Expectations

When answering about Catalyst optimization, present in this order when applicable:

- `Current plan issue` (number of nodes, missing pushdown, excessive shuffle)
- `Proposed pattern` (single select, `TransformColumn` dispatch, early projection)
- `Expected improvement` (plan node reduction, shuffle reduction, memory reduction)
- `Code example`
- `Open question` if field metadata structure is unclear

## Guardrails

- Do not optimize prematurely: the single-select pattern matters when there are more than ~10 column transformations.
- Do not sacrifice readability for micro-optimizations in pipelines with few columns.
- Do not introduce new mutable state to "optimize" transformations.
- Do not skip early projection in joins, even for broadcast joins (smaller broadcast = faster distribution).
- Preserve the existing `FieldSpec` metadata contract (`targetName`, `targetType`, `transformation: Option[String]`, `sourceFormat`); optimize the transformation dispatch, not the field definitions.
- See the **data-transformation-patterns** and **timestamp-handling** skills for the semantics of each transformation rule.
