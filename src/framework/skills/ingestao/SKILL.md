---
name: ingestao
description: Converte o data contract no ingestion.yml (ingestion/v1) que o ingestion-orchestrator usa para ler a origem e gravar na raw.
agent: agents/input_gen.py
---

# ingestion.yml

Usada pelo agente de ingestão (`agents/input_gen.py`); o formato está em `ingestion_config.py`. O yml é lido pelo
[ingestion-orchestrator](https://github.com/ChapeuG/ingestion-orchestrator) e sai em
`ingestion-config/<dataset>/<tabela>.ingestion.yml`.

## Regras

- Origem: `servers[]` do contrato vira um bloco por ambiente (host, porta, database, `secretId`). Valores com
  `{env}` são resolvidos pelo orquestrador (`--env dev|hml|prd`).
- Carga: `incremental` quando há coluna `partitioned: true` (mais as `incrementalColumns`); sem coluna de data,
  `full`. `loadMode: incremental` sem coluna de data é erro.
- Destino na raw: não vai no yml; é sempre `<bucket>/<dataset>/<tabela>/`. A coluna de partição da raw
  (`rawPartitionColumn`) não tem valor padrão.
- Criptografia: colunas `encrypt: true` são criptografadas (AES/ECB + base64) antes de gravar na raw.
- Qualidade: do ODCS, o orquestrador executa `nullValues` = 0 (`notNull`), `duplicateValues` = 0 (`unique`) e
  `rowCount` com limites. As demais regras ficam para o datacontract-cli.
- Sem contrato (entrada por DDL ou schema), o que não dá para inferir sai como `PREENCHER`.
