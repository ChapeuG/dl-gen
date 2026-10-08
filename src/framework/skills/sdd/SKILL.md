---
name: sdd
description: Escreve o SDD (documento de especificação) da tabela, com as seções que o framework já sabe preencher e as pendentes marcadas.
agent: agents/transform_gen.py
---

# SDD da tabela

Gerado junto com a transformação, a partir de `templates/transformation/sdd_doc.md.j2`, em
`docs_sdd/<tabela>_sdd_doc.md`. Seções marcadas como **Informação pendente** precisam ser completadas por quem
desenvolve antes de subir o projeto.

## Seções

1. Identificação — tabela, database, comentário e origem (banco + caminho do ingestion.yml).
2. Particionamento — partição de dados e de atualização (skill `transformacao`); pendente quando foi inferida.
3. Chave de merge — colunas e de onde vieram (`--merge-keys`, PK, heurística).
4. Schema — os campos principais (origem → staging, tipo, transformação, descrição).
5. Campos aninhados (NestedField) — hoje todos os campos saem flat.
6. Regras de negócio — criptografia e centavos já preenchidos; domínios e regras condicionais pendentes.
7. Enrichments — pendente (joins com tabelas de lookup).
8. Joins inter-tabelas — preenchida com as `relationships` (chaves estrangeiras) do contrato.
9. Transformações — o que cada transformação padrão faz por tipo.
10. Escrita e persistência — Delta, MERGE null-safe, tabela Hive e file sizing estimado.
