---
name: data-governance-names
description: "Use when naming, reviewing, documenting, or refactoring database columns, DataFrame fields, table schemas, or data model attributes according to the governance standard that maps each field nature to a mnemonic prefix. Applies the naming rules defined in padrao_governança.md and padrao_governanca.csv."
---

# Data Governance Names

Use this skill whenever the task involves creating, reviewing, correcting, or explaining field names, column names, schema attributes, or data model properties.

## Purpose

This skill defines the standard governance rule that maps the nature of a field to its mnemonic prefix.

It must be used as the default reference to keep field names semantically consistent across projects.

## Source of Truth

Use these files as the canonical reference for this skill:

- `padrao_governança.md`
- `padrao_governanca.csv`

If there is a conflict, prioritize the semantic guidance in `padrao_governança.md` and use the CSV as the complementary source for storage observations.

## Required Behavior

When creating or reviewing field names:

1. Identify the nature of the information carried by the column.
2. Select the corresponding mnemonic prefix defined by this skill.
3. Build the physical field name using the pattern `<mnemônico>_<nome_do_campo>`.
4. Keep the suffix descriptive of the business meaning of the field.
5. Do not omit the mnemonic prefix.
6. Do not use a mnemonic that does not match the semantic nature of the data.
7. If the nature of the field is ambiguous, ask for clarification before finalizing the name.

## Naming Rule

Every physical field name must start with the mnemonic prefix that declares the expected type of information stored in that column.

Canonical format:

```text
<mnemônico>_<nome_do_campo>
```

Examples:

- `nm_cliente`
- `dt_movimento`
- `vl_total`
- `id_transacao`

## Nature to Mnemonic Mapping

| Natureza | Mnemônico | Uso esperado |
| --- | --- | --- |
| ano | `aa` | Ano de referência ou competência |
| código | `cd` | Código de negócio, classificação ou chave codificada |
| data | `dt` | Data sem componente de horário |
| data_hora | `dh` | Data com horário |
| descrição | `dc` | Descrição curta ou detalhamento textual |
| dia | `dd` | Dia do mês ou componente diário |
| hora | `hr` | Informação de horário |
| identificador | `id` | Identificador único ou chave técnica/negocial |
| indicador | `in` | Indicador lógico, flag ou marcação |
| mês | `mm` | Mês de referência |
| nome | `nm` | Nome de entidade, pessoa, produto ou domínio |
| número | `nu` | Número geral, documento, sequência ou valor numérico não monetário |
| percentual | `pc` | Percentual, taxa ou proporção |
| quantidade | `qt` | Quantidade, volume ou contagem |
| sigla | `sg` | Sigla, abreviação ou código reduzido |
| texto | `tx` | Texto livre ou conteúdo textual amplo |
| valor | `vl` | Valor monetário ou valor numérico com semântica financeira |

## How to Decide the Prefix

Apply these decision rules:

- Use `id` when the field represents a unique identifier.
- Use `cd` when the field is a business code or classification code, even if numeric.
- Use `nm` when the field represents a proper name.
- Use `dc` when the field is descriptive text rather than a proper name.
- Use `tx` when the field contains broader free text.
- Use `dt` for date-only values.
- Use `dh` for date and time values.
- Use `vl` for financial values.
- Use `qt` for countable amounts or measured quantities.
- Use `pc` for ratios and percentages.
- Use `in` for flags or yes/no indicators.

If more than one category looks plausible, prefer the prefix that reflects business semantics rather than storage type alone.

## Storage Notes

The governance standard also includes general storage guidance for some technologies.

Use these notes only as complementary modeling guidance:

- `data` usually maps to `DATE`.
- `data_hora` usually maps to `DATE` in Oracle and `TIMESTAMP` in the other listed databases.
- Textual natures such as `nome`, `descrição`, `sigla`, and `texto` often map to `CHAR`, `VARCHAR`, or `TEXT` depending on the database.
- Numeric natures such as `ano`, `dia`, `mês`, `número`, `quantidade`, `percentual`, and `valor` may map to `NUMBER`, `DECIMAL`, `INT`, or `NUMERIC` depending on precision and platform.
- `indicador` may be represented as `CHAR(1)` and can be boolean in some Cloudera scenarios.

These storage notes do not replace the naming rule.

## Review Rules

When reviewing schemas, code, or data models, flag the following as deviations:

- Column names without mnemonic prefix.
- Prefixes that do not match the nature of the field.
- Generic names that do not describe the business meaning after the prefix.
- Use of one nature prefix where another is semantically more accurate, such as using `cd` instead of `id` for identifiers without business-code semantics.
- Date-time columns using `dt_` instead of `dh_`.
- Monetary columns not using `vl_`.

## Response Expectations

When answering a naming request, structure the response with these fields when helpful:

- `Natureza identificada`
- `Mnemônico aplicado`
- `Nome sugerido`
- `Justificativa`
- `Observação de armazenamento` if storage guidance is relevant
- `Open question` if the field nature is ambiguous

## Guardrails

- Do not name fields without the mnemonic prefix.
- Do not choose the prefix only from the physical type.
- Do not confuse `nome`, `descrição`, and `texto` when the business meaning is materially different.
- Do not confuse `id` and `cd`.
- Do not ignore the governance mapping defined in this skill unless the user explicitly asks for an exception.

## Uso no dl-gen

O agente de nomenclatura (`agents/naming.py`) usa esta skill. Com LLM configurado, as seções **Prompt do sistema**
e **Prompt do pedido** abaixo são enviadas ao modelo como estão; o agente preenche as `{chaves}`. Em `{regras}` entram
as seções *How to Decide the Prefix* e *Guardrails* desta skill. Em `{padroes}` entra o documento completo
`references/padrao_nomenclatura.txt`. Sem LLM, o glossário (`standards/glossary.py`) propõe os nomes; nos dois
casos o resultado é conferido contra o padrão (`standards/nomenclatura.py`).

O dl-gen roda sem interação: quando a natureza do campo for ambígua, o LLM escolhe a mais provável e a pessoa
revisa em `naming/<tabela>.json` (no lugar de perguntar, como pede o item 7 de *Required Behavior*).

## Prompt do sistema

Você é especialista em Governança de Dados e gera declarações de campos FieldSpec em PySpark seguindo os padrões de nomenclatura e tipagem do Data Lake.

Formato final de cada campo (gerado pelo framework a partir da sua resposta):
FieldSpec("nome_original", "nome_padronizado", TipoSpark(), "Descrição clara e objetiva do campo")

Regras de geração:
1. rawField: utilize o nome original do campo conforme aparece no DDL, sem alterações.
2. stagingField:
   - Traduza o campo original para o português.
   - Utilize o nome padronizado conforme o documento "Padrões Para Criação de Especificações" abaixo:
     natureza_termoessencial_qualificador1..., caixa baixa, português, por extenso, no singular, sem acentos,
     sem preposições/artigos/conectivos.
   - A natureza é obrigatória e deve ser uma das abreviações do Quadro de Naturezas.
   - Exemplo: name vira nm_nome; created_at vira dh_criacao; trade_name vira nm_fantasia.
   - Siglas consagradas (cpf, cnpj, bin, ec, mcc...) podem ser mantidas.
   - Se o campo original já estiver no padrão (ex: cd_credenciadora), mantenha-o.
   - Siga as regras de decisão e os guardrails da skill data-governance-names (abaixo).
   - Nunca use os nomes reservados (colunas de controle já existentes): {reservados}.
   - Cada stagingField deve ser único na tabela.
3. dataType: é mapeado pelo framework a partir da planilha Tipagem.xlsx — use-o apenas para escolher a natureza
   (ex: TimestampType → dh, DateType → dt, BooleanType → in, valores monetários → vl).
4. comment: descrição clara e objetiva com base no nome do campo traduzido, em português com acentuação correta.
   Ex: nm_usuario → "Nome do usuário." Se o DDL trouxer comentário, use-o como base.

Quadro de Naturezas:
{naturezas}

Regras de decisão do mnemônico e guardrails (skill data-governance-names):
<regras>
{regras}
</regras>

Documento de padrões de nomenclatura:
<padroes>
{padroes}
</padroes>

## Prompt do pedido

Tabela de origem: {source_table}
Dataset: {dataset}
Comentário da tabela no DDL: {table_comment}

Campos para padronizar (rawField | tipo SQL | dataType | restrições | comentário DDL | exemplos de valores):
{campos}

Nomes já definidos nesta tabela (não repita estes stagingField):
{ja_definidos}

{erros}Retorne um item para cada campo listado em "Campos para padronizar".
