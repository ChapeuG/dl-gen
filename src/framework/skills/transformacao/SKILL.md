---
name: transformacao
description: Monta o projeto <dataset>-transformation (raw → staging Delta + tabela Hive) no padrão heavy-transformation, em PySpark ou Scala.
agent: agents/transform_gen.py
---

# Projeto de transformação (heavy-transformation)

Usada pelo agente de transformação (`agents/transform_gen.py`). Não chama LLM: o código aplica as regras abaixo e
renderiza os templates de `templates/transformation/pyspark/` ou `templates/transformation/scala/`. Os utilitários
de `static/` são copiados 1:1 para o projeto gerado.

## Estrutura gerada

| PySpark (padrão) | Scala (sbt) |
|---|---|
| `main.py` (`--table_name` escolhe o processor) | `src/main/scala/br/com/datalake/Main.scala` |
| `datalake/processor/<tabela>/<tabela>_model.py` | `processor/<tabela>/<Tabela>Model.scala` |
| `datalake/processor/<tabela>/<tabela>_processor.py` | `processor/<tabela>/<Tabela>Processor.scala` |
| `datalake/utils/`, `datalake/error/` | `utils/`, `error/` |
| `pyproject.toml` | `build.sbt`, `project/` |

Nas duas: `docs_sdd/<tabela>_sdd_doc.md` (skill `sdd`), `.github/workflows/pipeline.yml` e `catalog-info.yaml`.

## Fluxo do processor

Parâmetros → leitura da raw (JSON, tudo StringType) → rename raw → staging → transformações num único select →
colunas de partição → enrichments → deduplicação (mais recente por chave de merge) → rastreabilidade → Delta
(overwrite na primeira carga, MERGE null-safe depois) → tabela Hive/Athena com schema evolution.

## Regras dos campos (FieldSpec)

- Origem em minúsculo (a ingestão grava as colunas assim); destino = nome da staging (skill `nomenclatura`).
- Transformação padrão por tipo: `default` (TRIM/UPPER em texto, cast nos demais); nenhuma em identificadores
  (`id_*`, uuid), datas guardadas como texto (`dt`/`dh`/`hr`), arrays e colunas criptografadas; `centavos` nos
  campos monetários detectados na amostra.
- Coluna criptografada ou array chega na raw como texto: o tipo fica `StringType`.
- Sempre há a coluna de controle `dh_criacao_data_lake` (vinda de `@timestamp` da ingestão).
- O arquivo `naming/<tabela>.json` pode trocar a transformação (`"transformation"`) e o formato de origem
  (`"source_format"`) de cada campo.

## Chave de merge e partições

- Chave: `--merge-keys` (ou `primaryKey` do contrato) > PK do DDL > primeiro campo NOT NULL (com aviso). Sem
  nenhum, a geração para com erro.
- Partição de dados `dt_<termo>_particao` (yyyyMMdd) a partir da coluna de data escolhida (ou `created*`) e
  partição de atualização `dt_atualizacao_registro_particao` (data do processamento).
