---
name: fact-to-fact-joins
description: "Use when joining the main fact DataFrame with another fact (complement) Delta table — partition-pruned left_outer join, dropping conflicting system columns, and applying renames on the complement side before the join. Distinct from enrichment-joins (broadcast of small dimensions). Implements the FactRightJoin pattern and its JoinSpec contract."
---

# Fact-to-Fact Joins (FactRightJoin)

Use this skill whenever the task joins the main fact DataFrame with another **fact** (complement) table — not a small dimension. Examples: joining `pedido_consolidado` with `pedido_parceiro` and `pedido_internacional`.

## Purpose

This skill defines the canonical pattern for fact-to-fact joins via `FactRightJoin`:
- read the complement Delta table and **prune it by partition** before the join,
- drop the complement's **system columns** that would collide with the main after a `Seq[String]` join,
- apply optional **renames** on the complement side to align/deduplicate names,
- execute a `left_outer` join that preserves every record of the main fact.

It is **distinct** from the **enrichment-joins** skill, which broadcasts small dimension tables (< 10MB) with sequential aliasing. Fact complements are large and partition-filtered, so they are **not** broadcast — let Spark pick the plan.

## Required Behavior

1. Filter the complement by its partition column against the processing date **before** the join (pruning):

```scala
val complementRaw = spark.read.format("delta").load(complementPath)
  .filter(col(partitionColumn) === partitionDate)   // partitionColumn defaults to dt_atualizacao_registro_particao
```

`partitionDate` comes from the run-timestamp pattern (`--processing_date` or the run date). See the **processing-timestamp** skill.

2. Drop the complement's conflicting **system columns** (traceability + partitions), plus any table-specific extra drops:

```scala
private val systemColumnsToDrop: Seq[String] = Seq(
  "dh_criacao_registro",
  "dh_atualizacao_registro",
  "dt_atualizacao_registro_particao",
  "dt_local_transacao_bit13_particao",
  "dh_criacao_data_lake"
)
val allDrops = (systemColumnsToDrop ++ extraDropsFromComplement).distinct
val dropCols = allDrops.filter(complementRaw.columns.contains)
```

Dropping is required because the join uses `Seq[String]` keys; any non-key column present on both sides would otherwise become ambiguous/duplicated.

3. Apply renames on the complement side before the join (name harmonization, or renaming the complement's join key to match the main's):

```scala
val complementRenamed = DataFrameUtils.renameColumns(complementCleaned, renames)
```

4. Execute a `left_outer` join keyed by the business keys, preserving all main records:

```scala
main.join(complementRenamed, joinKeys, "left_outer")
```

See `scripts/FactRightJoin.scala` for the full implementation (mirrors production 1:1).

## The JoinSpec Contract

Per-table join constants live in a `JoinSpec` object next to the table's `Processor`/`Pipeline` (not in `utils/`). It carries:

- `joinKeys: Seq[String]` — business keys common to main and complement.
- `<complement>Renames: Map[String, String]` — renames applied to the complement before the join (may be empty).
- `<complement>Drops: Seq[String]` — extra complement columns to drop (fields whose canonical source is the main).

Example (abridged):

```scala
private[pedido_consolidado] object PedidoConsolidadoJoinSpec {
  val joinKeys: Seq[String] = Seq(
    "nu_identificacao_transacao_bit11",
    "nu_nsu_rede_captura_bit37",
    "dh_transmissao_bit07",
    "cd_tipo_pedido_consolidado"
  )
  val pedidoParceiroRenames: Map[String, String] = Map.empty
  val pedidoParceiroDrops: Seq[String] = Seq("nu_identificador_unico_transacao", "dt_local_transacao_bit13")
  val eloInternacionalRenames: Map[String, String] = Map(
    "nu_identificacao_transacao_stan_bit11" -> "nu_identificacao_transacao_bit11"
    // ...
  )
}
```

## Where It Sits in the Pipeline

Fact joins run in the enrich/join stage, interleaved with dimension enrichments: direct enrichments → fact join (pedido_parceiro) → its enrichments → fact join (pedido_internacional) → its enrichments. See the **processor-orchestration** skill.

## Review Rules

When reviewing fact-to-fact join code, flag the following as deviations:

- Missing partition filter on the complement before the join (full-table scan, no pruning).
- Broadcasting the complement fact table (it is partition-filtered and variable-size — do not broadcast).
- Not dropping conflicting system columns before a `Seq[String]` join (ambiguous columns / duplicated names).
- Join keys, renames, or drops hardcoded inside the join call instead of a `JoinSpec`.
- Using an inner/right join where `left_outer` is required to preserve all main records.
- Deriving `partitionDate` per-row instead of from the driver-side run timestamp.

## Guardrails

- Do not broadcast fact complements.
- Do not skip the partition filter — it is the pruning that makes the join affordable.
- Do not rename or drop columns on the **main** side inside this util; only the complement is cleaned/renamed here.
- Preserve `left_outer` semantics (all main rows kept).
- For small dimension lookups use **enrichment-joins**; for the pruning date use **processing-timestamp**.
