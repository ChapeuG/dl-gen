---
name: ingestao
description: "Use when generating, reviewing, or explaining the ingestion.yml (format ingestion/v1) read by the ingestion-orchestrator: source servers per environment, load mode (incremental/full), columns, encryption and quality rules derived from the ODCS data contract."
---

# Ingestão (ingestion.yml)

Use this skill whenever the task involves the ingestion side of a table: turning the data contract into the
`ingestion.yml` that the [ingestion-orchestrator](https://github.com/ChapeuG/ingestion-orchestrator) uses to read
the source and write to the raw layer.

## Purpose

The ingestion produces the raw data that the transformation (skills **project-structure**, **job-parameters**)
reads as `data_source`. In the dl-gen it is implemented by `agents/input_gen.py` and `ingestion_config.py`; the file
goes to `ingestion-config/<dataset>/<tabela>.ingestion.yml`.

## Required Behavior

1. Source: each `servers[]` entry of the contract becomes a block per environment (host, port, database,
   `secretId`). Values with `{env}` are resolved by the orchestrator (`--env dev|hml|prd`).
2. Load mode: `incremental` when there is a `partitioned: true` column (plus `incrementalColumns`); without a date
   column, `full`.
3. Raw destination: not in the yml; it is always `<bucket>/<dataset>/<tabela>/`. The raw partition column
   (`rawPartitionColumn`) is always informed in the contract.
4. Encryption: columns with `encrypt: true` are encrypted (AES/ECB + base64) before being written to the raw layer;
   in the transformation they keep `transformation=null` (skill **data-transformation-patterns**).
5. Quality: from the ODCS rules, the orchestrator runs `nullValues` = 0 (`notNull`), `duplicateValues` = 0 (`unique`)
   and `rowCount` with bounds. Other rules are left to the datacontract-cli.
6. Without a contract (input by DDL or schema), whatever cannot be inferred is written as `PREENCHER`.

## Guardrails

- Do not set a default for the raw partition column.
- Do not accept `loadMode: incremental` without a date column.
- Do not put credentials in the yml: only the secret ARN (`secretId`).
- Do not leave sensitive columns (cpf, cnpj, email...) unencrypted without flagging it.
