---
name: job-parameters
description: "Use when defining, validating, documenting, or generating Spark job parameters, especially the core inputs table_name, data_source, and output_uri (plus optional database, s3_base_path, secret_arn). Applies the canonical parameter contract for Spark processing jobs in this workspace."
---

# Spark Job Parameters

Use this skill whenever the task involves creating, reviewing, validating, or explaining the parameters required to run a Spark job.

## Purpose

This skill defines the mandatory parameter contract for Spark processing jobs in this workspace.

When the agent generates code, documentation, examples, or validation logic for Spark jobs, it must follow these parameter rules.

## Required Behavior

When handling job parameters for a Spark process:

1. Treat only the **core** parameters as mandatory: `table_name`, `data_source`, `output_uri`. Everything else is optional with a defined default/fallback.
2. Do not describe the job as executable unless all mandatory core parameters are present.
3. If any mandatory parameter is missing, explicitly point it out and ask for the missing value.
4. Preserve the exact CLI parameter names defined here unless the user explicitly requests a rename.
5. When generating Scala code, argument parsing, or documentation, keep the same semantic meaning for each parameter.
6. If a value is provided but ambiguous, ask for clarification before finalizing the solution.
7. Assume the parameters are passed in Linux command-line style, using `--parameter_name value`.
8. Do not treat domain-specific parameters as part of the general contract — see "Project-specific parameters" below.

## Input Format

The job parameters must be provided in Linux CLI style.

Expected pattern:

```bash
--table_name tabelaA --data_source /path/input --output_uri s3://bucket/team/dataset/tabelaA
```

Optional flags follow the same style, e.g. `--database databaseA_qa`, `--s3_base_path s3://bucket`, `--secret_arn arn:aws:...`.

Interpretation rules:

- Each parameter is passed as a named flag prefixed with `--`.
- Each flag must be followed by its value.
- The agent must preserve this format when generating execution examples, documentation, or argument parsing code.
- The table parameter is received externally as `--table_name`.

## Core Parameters (mandatory)

### `table_name`

Meaning:
- Name of the table that will be created or populated by the processing job. Also selects which processor runs (see the **project-structure** skill).

Usage rule:
- Mandatory.
- Must identify the target table of the Spark processing result.

Agent guidance:
- Use this parameter whenever defining write targets, table registration, save logic, or output metadata.

### `data_source`

Meaning:
- Path where the input files to be processed are stored.

Usage rule:
- Mandatory.
- Must identify the source location read by the Spark job.

Agent guidance:
- Use this parameter in read operations such as file loading, ingestion setup, and source validation.

### `output_uri`

Meaning:
- Path where the processed output must be saved.

Usage rule:
- Mandatory.
- Must identify the storage destination for the processed data.
- Must follow the standard AWS S3 output structure defined in this skill.

Agent guidance:
- Use this parameter in write operations, persistence flows, and output publication logic.

## Output Path Standard

The output path must always follow this AWS S3 prefix pattern:

```text
s3://<bucket-name>/<team>/<dataset>/<table>
```

Interpretation rules:

- `<bucket-name>` is the destination S3 bucket.
- `<team>` identifies the owning team domain in the bucket path.
- `<dataset>` identifies the logical dataset segment in the path.
- `<table>` identifies the target table segment in the path.

### Dataset and Database Mapping

The `dataset` segment in `output_uri` is environment-dependent and must be derived from `database` as follows:

- In production, `dataset` is the same value as `database`.
- In QA or homologation, `database` is the dataset name with suffix `_qa`.
- In development, `database` is the dataset name with suffix `_dev`.

Examples:

- Production: `dataset=customer`, `database=customer`
- QA: `dataset=customer`, `database=customer_qa`
- Development: `dataset=customer`, `database=customer_dev`

Agent guidance:

- Do not assume that the full `database` value should always be copied verbatim into the S3 dataset segment.
- When building `output_uri`, use the base dataset name in the path and apply environment suffixes only to `database` in non-production environments.
- If the environment is not clear, ask whether the job targets production, QA, or development before finalizing the path.

## Optional Parameters (with defaults / fallbacks)

### `database`

Meaning:
- Logical destination database for the target table.

Usage rule:
- Optional. When absent, defaults to the model's `databaseName` (`params.getOrElse("database", model.databaseName)`).
- Combine with `table_name` to build the fully qualified table reference (`database.table_name`).

Agent guidance:
- Do not flag a job as incomplete only because `database` is absent; the model provides the default.

### `s3_base_path`

Meaning:
- Base S3 path (`<basePath>`) under which lookup/complement tables live, following `<basePath>/<team>/<dataset>/<table>`.

Usage rule:
- Optional. When absent, it is **derived from `output_uri`** by dropping the last three segments — `FileUtils.deriveBasePathFromTableUri(output_uri)`.
- Keep this fallback: it lets a job locate enrichment/complement tables without an extra parameter, assuming they share the base path of the output.

Agent guidance:
- When generating code that reads lookup/complement tables, resolve the base path as `params.get("s3_base_path").filter(_.nonEmpty).getOrElse(FileUtils.deriveBasePathFromTableUri(output_uri))`.
- Do not require this parameter; require the derivation function instead.

### `secret_arn`

Meaning:
- AWS Secrets Manager ARN identifying the secret with the key material used in AES encryption.

Usage rule:
- Optional. Only relevant when the job performs encryption. The authorization project ships the retrieval util (`SecretsManager`) but does **not** currently use encryption, so this parameter is not required there.
- Treat this ARN as the source reference for secret retrieval, never as the secret value itself.

Agent guidance:
- Require it only when the specific job actually encrypts PII; otherwise treat it as absent-by-default.

## Project-specific parameters

Some jobs add parameters that are **specific to their domain** and are NOT part of the general contract. Do not assume them for other projects; document them as extensions of the job that defines them. In the authorization pipeline these are:

- `--processing_date` (`yyyyMMdd`): partition filter used to prune the complement tables in the fact-to-fact join (see the **fact-to-fact-joins** and **processing-timestamp** skills). Defaults to the run date when absent.
- `--sqs_arn`: SQS queue ARN for error notifications (see the **error-handler** skill).
- `--pedido_parceiro_uri`, `--pedido_internacional_uri`: explicit overrides for the complement-table paths; otherwise derived from `s3_base_path`.

## Canonical Interpretation

The agent must interpret the parameters like this:

- `table_name`: business output object name and processor selector (mandatory)
- `data_source`: physical input path (mandatory)
- `output_uri`: physical output path (mandatory)
- `database`: logical catalog/schema destination (optional → model default)
- `s3_base_path`: base path for lookup/complement tables (optional → derived from `output_uri`)
- `secret_arn`: AWS Secrets Manager reference for the encryption secret (optional → only when encrypting)

For `output_uri`, the agent must also interpret:

- `dataset`: base logical dataset name used in the S3 path
- `database`: environment-specific logical database name derived from the dataset in non-production environments

## Validation Rules

Flag as incomplete any Spark job request that does not include the three mandatory core parameters.

Specifically:

- Missing `table_name`: the target table (and processor) is undefined.
- Missing `data_source`: the input location is undefined.
- Missing `output_uri`: the output destination is undefined.

If any of these three are absent, the agent must ask for the missing parameter instead of silently assuming a default.

Do NOT flag as incomplete when only optional parameters are missing — `database` (model default), `s3_base_path` (derived from `output_uri`), or `secret_arn` (only when encrypting).

Also flag as incomplete any request where `output_uri` does not match the expected S3 structure or where the environment-to-database mapping is ambiguous.

## Scala Spark Guidance

When generating Scala examples, parameter handling should make the contract explicit.

This project parses args into a `Map[String, String]` (see the **project-structure** skill's `ArgsParser`). Mandatory keys are read directly; optional keys use `getOrElse` with the defined default/fallback:

```scala
val dataSource = params("data_source")     // mandatory
val outputPath = params("output_uri")      // mandatory
val database   = params.getOrElse("database", model.databaseName)  // optional -> model default
val fullTableName = s"$database.${model.tableName}"

// optional s3_base_path with derivation fallback
val s3BasePath = params.get("s3_base_path").filter(_.nonEmpty)
  .getOrElse(FileUtils.deriveBasePathFromTableUri(outputPath))
```

Output path examples:

```text
Production:
s3://my-bucket/my-team/customer/orders

QA:
s3://my-bucket/my-team/customer/orders
database=customer_qa

Development:
s3://my-bucket/my-team/customer/orders
database=customer_dev
```

If the codebase uses another parameter structure, such as `Map[String, String]`, CLI args, or a config object, preserve the local implementation style but keep the same required fields and meanings.

## Review Rules

When reviewing code or documentation, flag the following as deviations:

- Missing one or more mandatory core parameters (`table_name`, `data_source`, `output_uri`).
- Flagging a job as incomplete for a missing optional parameter that has a default/fallback.
- A domain-specific parameter (e.g. `processing_date`) presented as part of the general contract.
- Requiring `s3_base_path` instead of deriving it from `output_uri` when absent.
- Renamed parameters without explicit justification.
- Confusion between `data_source` and `output_uri`.
- Confusion between `secret_arn` and the secret value used in encryption.
- Confusion between physical output path and logical table destination.
- `output_uri` values that do not follow `s3://<bucket-name>/<team>/<dataset>/<table>`.
- `output_uri` examples that use the suffixed database name in place of the base dataset path for QA or development.
- Examples that write data without clearly identifying both destination path and destination table context when both are expected by the job contract.
- Examples that do not follow Linux CLI flag format such as `--table_name tabelaA --database databaseA`.
- Encryption examples that omit `--secret_arn`.

## Response Expectations

When answering a Spark job parameter request, structure the response with these fields when helpful:

- `Required parameters`
- `Missing parameters`
- `Parameter meaning`
- `Scala example`
- `Open question` if any required value is absent or ambiguous

## Guardrails

- Do not invent default values for the mandatory core parameters (`table_name`, `data_source`, `output_uri`).
- Do use the defined defaults for optional parameters: `database` → model default; `s3_base_path` → derived from `output_uri`.
- Do not assume `database.table` when `table_name` is missing (a missing `database` is fine — it defaults).
- Do not assume input or output storage paths.
- Do not build `output_uri` outside the required S3 prefix pattern.
- Do not use `database_qa` or `database_dev` directly as the dataset path segment in S3.
- Do not hardcode encryption keys or substitute them for `secret_arn`.
- Do not collapse `data_source` and `output_uri` into a single parameter.
- Preserve the exact mandatory parameter names unless the user explicitly requests a different public contract.
