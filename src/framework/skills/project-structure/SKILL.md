---
name: project-structure
description: "Use when creating, reviewing, documenting, or refactoring the standard structure of Spark projects in Scala with sbt. Applies the canonical project layout, package organization, and execution flow based on Main.scala, table models, and processors."
---

# Spark Project Structure

Use this skill whenever the task involves defining, generating, reviewing, or validating the standard structure of a Spark project in Scala.

## Purpose

This skill defines the canonical project layout for Spark applications in this workspace.

It must be used as the default reference to keep project organization consistent across implementations.

## Required Behavior

When creating or reviewing a Spark project:

1. Follow the directory structure defined in this skill unless the user explicitly requests an exception.
2. Keep `Main.scala` as the application entry point.
3. Use `table_name` as the routing parameter that identifies which process must run.
4. Resolve the processing flow through the corresponding `TableModel` and activate the matching `TableProcessor`.
5. Keep table-specific logic isolated inside the corresponding subdirectory under `processor/`.
6. Keep reusable utilities inside `utils/`.
7. Preserve the package base `br/com/datalake/` unless the user explicitly changes the organization namespace.

## Standard Project Layout

Expected structure:

```text
<project-name>/
├── build.sbt
├── project/
│   ├── build.properties
│   └── plugins.sbt
└── src/main/scala/br/com/datalake/
		├── Main.scala
		├── error/
		│   └── SparkErrorHandler.scala        # classificacao de erros + SparkErrorResult
		├── processor/
		│   ├── table_a/                        # tabela simples: Model + Processor
		│   │   ├── TableAModel.scala
		│   │   └── TableAProcessor.scala
		│   └── table_b/                        # tabela complexa: split de responsabilidades
		│       ├── TableBModel.scala           # schema, campos, enrichments, merge keys
		│       ├── TableBProcessor.scala       # orquestracao (params, persist, write, Hive)
		│       ├── TableBPipeline.scala        # transformacoes puras (read/staging/cast/enrich)
		│       └── TableBJoinSpec.scala        # constantes de join fato-a-fato (keys/renames/drops)
		└── utils/
				├── TableModel.scala               # trait de modelo
				├── FieldSpec.scala                # spec de campo direto
				├── NestedFieldSpec.scala          # spec de subcampo posicional
				├── TransformColumn.scala          # dispatch (targetType, transformation)
				├── DataFrameUtils.scala           # rename / substringExtract / traceability
				├── ApplyEnrichment.scala          # broadcast join de dimensoes
				├── Enrichment.scala               # contrato de enrichment
				├── FactRightJoin.scala            # join fato-a-fato particionado
				├── DeltaWritePattern.scala        # dedup / merge / overwrite / manifesto
				├── HiveTableManager.scala         # DDL / schema evolution / particoes
				├── NormalizeTimestamp.scala       # UDF de normalizacao de string timestamp
				├── RegexExtractors.scala          # UDFs de extracao por regex (dominio-especifico)
				├── FileUtils.scala                # construcao/derivacao de paths S3
				├── ArgsParser.scala               # parsing de --chave valor
				├── SecretsManager.scala           # recuperacao de segredo (AWS Secrets Manager)
				└── SqsUtils.scala                 # notificacao de erro para SQS
```

Notes:
- A **simple** table (single source, no fact-to-fact joins) needs only `Model` + `Processor`.
- A **complex** table (e.g. the consolidated `pedido_consolidado`) splits into `Processor` (orchestration), `Pipeline` (pure transformations), and `JoinSpec` (join constants). See the **processor-orchestration** skill.
- Not every util applies to every project; several have dedicated skills (`DeltaWritePattern` → **delta-write-patterns**, `HiveTableManager` → **hive-table-management**, `ApplyEnrichment`/`Enrichment` → **enrichment-joins**, `FactRightJoin` → **fact-to-fact-joins**, `NestedFieldSpec`/`RegexExtractors` → **nested-field-extraction**, `TransformColumn` → **catalyst-optimization**, `NormalizeTimestamp` → **timestamp-handling**).

## Build Standard

The build definition in this project uses:

- `project/build.properties`: `sbt.version = 1.5.8`
- `project/plugins.sbt`: `sbt-assembly` `2.3.0` (plus `sbt-ide-settings` `1.1.2`)

Build (from `build.sbt`): Scala `2.12.20`, Spark `3.5.6` (provided), Delta `3.3.0`, AWS SDK v1 (`secretsmanager`, `sqs`); assembly jar `transformation.jar` with `assemblyOption ~= { _.withIncludeScala(false) }`.

Agent guidance:

- Preserve the existing versions; do not bump them unless the task explicitly asks for version alignment.
- When creating a new project from scratch, reuse these versions as the baseline.

## Component Responsibilities

### `Main.scala`

Responsibility:
- Entry point of the Spark application.
- Receive and validate input parameters.
- Identify which process must be executed based on `table_name`.

Required behavior:
- Parse the job parameters.
- Read `table_name`.
- Resolve the corresponding model.
- Trigger the correct processor.

Agent guidance:
- Do not place table-specific transformation logic directly in `Main.scala`.
- Keep `Main.scala` focused on orchestration and dispatch.

### `processor/<table_name>/TableXModel.scala`

Responsibility:
- Represent the table identity and metadata needed to route processing.
- Declare the table name handled by that processing unit.

Required behavior:
- Each table-specific folder must contain a model for that table.
- The model must expose the table identity used by `Main.scala` to choose the processor.

Agent guidance:
- Use the model as the reference that connects `table_name` to its processor.

### `processor/<table_name>/TableXProcessor.scala`

Responsibility:
- Implement the processing logic for one specific table.

Required behavior:
- Keep the processor isolated to a single table domain.
- Execute the read, transformation, enrichment, dedup, persist, and write flow for that table (see the **processor-orchestration** skill for the canonical step sequence).
- Resolve the run timestamp once at the start of the processor (see the **processing-timestamp** skill).

Agent guidance:
- Do not centralize multiple table implementations in one processor class.
- Prefer one processor per table.
- For complex tables, move pure transformations into a `Pipeline` object and join constants into a `JoinSpec` object, keeping the `Processor` focused on orchestration.

### `utils/`

Responsibility:
- Store reusable shared components used by multiple processors.

Foundational reference scripts (shipped with this skill, mirroring production 1:1):
- `TableModel.scala`: see `scripts/TableModel.scala`
- `FieldSpec.scala`: see `scripts/FieldSpec.scala`
- `ArgsParser.scala`: see `scripts/ArgsParser.scala`
- `SecretsManager.scala`: see `scripts/SecretsManager.scala`
- `SqsUtils.scala`: see `scripts/SqsUtils.scala`

The remaining utilities have their own dedicated skills:

> For Delta write patterns (merge, overwrite, dedup), see the **delta-write-patterns** skill.
> For Hive/Athena table management (CREATE TABLE, schema evolution, partition registration), see the **hive-table-management** skill.
> For dimension broadcast joins, see the **enrichment-joins** skill; for fact-to-fact joins, the **fact-to-fact-joins** skill.
> For positional/substring extraction, see the **nested-field-extraction** skill.
> For the column transform dispatch, see the **catalyst-optimization** skill; for timestamp normalization, the **timestamp-handling** skill.

Agent guidance:
- Place cross-project helpers here.
- Do not move table-specific business rules into `utils/` (e.g. join key constants belong in the table's `JoinSpec`).

## Routing Standard

The execution flow must follow this sequence:

1. `Main.scala` receives the job parameters.
2. `Main.scala` reads `table_name`.
3. The application identifies the matching `TableModel`.
4. The matched model determines which `TableProcessor` must be activated.
5. The processor for that table executes the Spark job.

Canonical interpretation:

- `table_name` is the process selector.
- `TableModel` is the lookup or reference point for process resolution.
- `TableProcessor` is the concrete execution unit.

## Scala Guidance

When generating sample code, preserve the orchestration split between entry point, model, processor, and shared utilities.

Minimal example:

```scala
object Main {
	def main(args: Array[String]): Unit = {
		val params = ArgsParser.parse(args)   // Map[String, String]

		implicit val spark: SparkSession = SparkSession.builder()
			.appName(s"pedido-consolidado-${params("table_name")}")
			.enableHiveSupport()
			.getOrCreate()

		params("table_name") match {
			case TableAModel.tableName => TableAProcessor.process(params)
			case TableBModel.tableName => TableBProcessor.process(params)
			case other => throw new IllegalArgumentException(s"Unsupported table_name: $other")
		}
	}
}
```

This is only the structural pattern. Keep the final implementation aligned with local project conventions if the repository already defines helper abstractions.

## Review Rules

When reviewing a Spark project structure, flag the following as deviations:

- Missing `Main.scala` as the orchestration entry point.
- Table-specific logic implemented directly in `Main.scala`.
- Absence of table-specific `Model` and `Processor` pairing.
- Multiple unrelated tables implemented inside the same processor class.
- Shared reusable helpers placed inside a table folder instead of `utils/` (join constants are the exception — they live in the table's `JoinSpec`).
- Missing `SecretsManager.scala` **when the project actually performs encryption** (the authorization project ships it but does not currently encrypt, so its absence there is not a deviation).
- Package structure outside `src/main/scala/br/com/datalake/` without explicit justification.
- Missing `build.properties` or `plugins.sbt` under `project/`.

## Response Expectations

When answering about Spark project structure, organize the answer with these fields when helpful:

- `Project layout`
- `Main responsibility`
- `Model responsibility`
- `Processor responsibility`
- `Shared utilities`
- `Deviation` if the current project diverges from the standard

## Guardrails

- Do not collapse all processing logic into `Main.scala`.
- Do not use `table_name` only as metadata; it must control processor selection.
- Do not create generic processors that mix unrelated table flows.
- Do not place shared helper code inside table-specific folders (join constants in `JoinSpec` are the exception).
- Do not remove `SecretsManager.scala` from the utility set when encryption is part of the project.
- Preserve this structure as the default standard across projects unless the user explicitly asks for a different architecture.
