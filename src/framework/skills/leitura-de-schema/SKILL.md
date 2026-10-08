---
name: leitura-de-schema
description: "Use when the table's fields come from something other than a CREATE TABLE: a SELECT query, an Avro/JSON Schema/Spark StructType, a field list (CSV, spreadsheet, Markdown, DESCRIBE output) or a data file (parquet, CSV). Converts any input that carries field name and type into a DDL, so the rest of the flow (sdd-specification, data-governance-names) starts from the same place."
---

# Leitura de Schema

Use this skill whenever the source structure of a table is not given as a DDL and has to be read from another format
before the SDD and the field names are derived.

## Purpose

The SDD (skill **sdd-specification**) requires, as minimum information, "DDL ou lista de campos". This skill turns
any of those into a canonical `CREATE TABLE`, keeping name, type, nullability, primary key and comment of each field.
In the dl-gen it is implemented by `parsers/schema_reader.py`, used by `--ddl`/`--schema` and by "Importar colunas"
in the Studio.

## Required Behavior

1. Detect the format from the content (and the file extension for binary files):

   | Entrada | Reconhecida por | Tipo vem de |
   | --- | --- | --- |
   | DDL | `CREATE TABLE` | o próprio DDL (passa direto) |
   | Query | começa com `SELECT`/`WITH`, ou `CREATE VIEW/TABLE ... AS SELECT` | `CAST(x AS t)`, `x::t`, `CONVERT(t, x)`, literais, `count(*)`, `current_date` |
   | Avro (`.avsc`) | JSON com `"type": "record"` | `long`, `["null", "string"]`, `logicalType` (decimal, date, timestamp) |
   | JSON Schema | JSON com `properties` | `type` + `format` (`date`, `date-time`); `required` define NOT NULL |
   | StructType do Spark | JSON com `"type": "struct"` (`df.schema.json()`) | `integer`, `decimal(10,2)`, `array` |
   | Lista de campos | JSON `[{name, type}]`, CSV/TSV/`;`, Markdown, `.xlsx`, saída de `DESCRIBE` | a coluna de tipo |
   | Arquivo de dados | `.parquet` (schema do arquivo), `.csv`/JSON com registros | inferido dos valores |

2. Recognize field-list headers by meaning, ignoring accents and case: `tipo`/`type` (type), `descrição`/`comentário`
   (comment), `obrigatório`/`required`, `nulo`/`nullable`, `pk`/`chave`, and `nome`/`campo`/`coluna`/`column`/`field`
   (name). Ex: "Nome do Campo", "Tipo de Dado", "Descrição".
3. Translate types from other formats into SQL types (`long` → `bigint`, `string` → `varchar`, `float64` → `double`,
   `struct`/`map` → `json`, `array<t>` → `t[]`); the official typing (`standards/tipagem.py`) then maps them to Spark.
4. Take the table name from the content (CREATE VIEW, FROM, Avro `name`, JSON Schema `title`) or from the file name,
   keeping the source schema (`loja.cliente` → table `cliente`, source `loja.cliente`).

## Guardrails

- Do not guess a type for a query column without `CAST`: use `varchar` and mark the comment
  "tipo não informado na origem (assumido texto)" so it is reviewed.
- Do not accept `SELECT *`: ask for the explicit column list.
- Do not treat a sample as proof of NOT NULL: columns inferred from data files stay nullable.
- Do not accept free text without a header unless every type in it is a known type.
- Do not rename fields here: naming belongs to **data-governance-names**.
