---
name: leitura-de-schema
description: Lê os campos e tipos da tabela de qualquer entrada (DDL, query, Avro, JSON Schema, StructType, lista de campos, planilha, parquet ou CSV de dados) e converte para DDL.
agent: parsers/schema_reader.py
---

# Leitura de schema

Usada na entrada (`--ddl`/`--schema` na linha de comando, "Importar colunas" no Studio). O código está em
`parsers/schema_reader.py`: ele converte a entrada num `CREATE TABLE` e o resto do framework segue igual
(`parsers/ddl_parser.py` → tipagem → nomenclatura...).

## Formatos aceitos

| Entrada | Como o formato é reconhecido | De onde vem o tipo |
|---|---|---|
| DDL | tem `CREATE TABLE` | do DDL (passa direto) |
| Query | começa com `SELECT`/`WITH`, ou `CREATE VIEW/TABLE ... AS SELECT` | `CAST(x AS t)`, `x::t`, `CONVERT(t, x)`, literais, `count(*)`, `current_date` |
| Avro (`.avsc`) | JSON com `"type": "record"` | `long`, `["null", "string"]`, `logicalType` (decimal, date, timestamp) |
| JSON Schema | JSON com `properties` | `type` + `format` (`date`, `date-time`), `required` define o NOT NULL |
| StructType do Spark | JSON com `"type": "struct"` (`df.schema.json()`) | `integer`, `decimal(10,2)`, `array` |
| Lista de campos | JSON `[{name, type}]`, CSV/TSV/`;`/Markdown, planilha `.xlsx`, saída de `DESCRIBE` | coluna de tipo |
| Arquivo de dados | `.parquet` (schema do arquivo), `.csv`/JSON com registros | inferido dos valores |

## Regras

- Lista de campos: o cabeçalho é reconhecido pelo sentido, sem acento nem caixa: `tipo`/`type` (tipo),
  `descrição`/`comentário` (comentário), `obrigatório`/`required`, `nulo`/`nullable`, `pk`/`chave`, e
  `nome`/`campo`/`coluna`/`column`/`field` (nome). Ex: "Nome do Campo", "Tipo de Dado", "Descrição".
- Texto solto sem cabeçalho (`nome tipo [comentário]` por linha) só é aceito se todos os tipos forem conhecidos.
- Coluna de query sem tipo vira `varchar` com o comentário "tipo não informado na origem"; revise na tabela de
  colunas. `SELECT *` é recusado: liste as colunas.
- Arquivo de dados: uma amostra não prova NOT NULL, então todas as colunas ficam anuláveis.
- Tipos de outros formatos viram tipos SQL (`long` → `bigint`, `string` → `varchar`, `float64` → `double`,
  `struct`/`map` → `json`, `array<t>` → `t[]`) e depois seguem a tipagem oficial (`standards/tipagem.py`).
- O nome da tabela vem do conteúdo (CREATE VIEW, FROM, `name` do Avro, `title` do JSON Schema) ou do nome do
  arquivo.
