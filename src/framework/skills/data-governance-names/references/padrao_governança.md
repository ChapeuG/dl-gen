# Padrão de Governança de Nomes

Este documento relaciona a natureza de um campo com o respectivo mnemônico utilizado na nomenclatura das colunas.

O mnemônico deve ser usado como prefixo do nome de cada campo para indicar o tipo de informação esperada naquela coluna.

Exemplos:

- `nm_cliente`: campo do tipo nome
- `dt_movimento`: campo do tipo data
- `vl_total`: campo do tipo valor
- `id_transacao`: campo do tipo identificador

## Regra Geral

- O nome físico da coluna deve começar pelo mnemônico da natureza do dado.
- Após o prefixo, usar um nome descritivo que represente o conteúdo do campo.
- O prefixo não substitui a descrição do campo; ele apenas qualifica semanticamente o tipo de informação.

## Relação Natureza x Mnemônico

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

## Orientação de Nomenclatura

Ao criar uma coluna, aplicar o padrão:

```text
<mnemônico>_<nome_do_campo>
```

Exemplos:

- `aa_referencia`
- `cd_produto`
- `dt_processamento`
- `dh_evento`
- `dc_status`
- `id_cliente`
- `in_ativo`
- `nm_fornecedor`
- `qt_parcelas`
- `vl_pagamento`

## Informações Complementares de Armazenamento

O CSV de origem também traz orientações gerais de tipagem física e lógica para alguns sistemas. Essas definições servem como apoio para modelagem, mas a principal função deste documento é padronizar a associação entre natureza e mnemônico.

### Regras Gerais Observadas

- Campos de `data` tendem a usar `DATE` em Oracle, MySQL, PostgreSQL e MariaDB.
- Campos de `data_hora` tendem a usar `DATE` em Oracle e `TIMESTAMP` nos demais bancos listados.
- Campos textuais como `nome`, `descrição`, `sigla` e `texto` podem ser representados por `CHAR(X)` ou `VARCHAR(X)`, com variações por banco.
- Campos numéricos como `ano`, `dia`, `mês`, `código`, `número`, `quantidade`, `percentual` e `valor` podem assumir `NUMBER`, `DECIMAL`, `INT` ou `NUMERIC`, conforme o banco e a precisão necessária.
- Campos do tipo `indicador` costumam ser armazenados como `CHAR(1)` e, em alguns cenários Cloudera, podem admitir representação booleana.
- Campos do tipo `identificador` dependem de decisão de modelagem e podem ficar a critério do DBA.

### Observações por Natureza

| Natureza | Observação geral de armazenamento |
| --- | --- |
| ano | Normalmente numérico com 4 dígitos |
| código | Pode ser numérico ou textual, dependendo da regra de negócio |
| data | Armazenamento orientado a `DATE` |
| data_hora | Armazenamento orientado a data e tempo, frequentemente `TIMESTAMP` fora de Oracle |
| descrição | Normalmente textual, com possibilidade de `CHAR`, `VARCHAR` ou `TEXT` |
| dia | Normalmente numérico com 2 dígitos |
| hora | Em geral armazenado como estrutura temporal |
| identificador | Tipo depende de decisão técnica e de modelagem |
| indicador | Em geral `CHAR(1)`, podendo ser booleano em alguns contextos |
| mês | Normalmente numérico com 2 dígitos |
| nome | Normalmente textual, com `CHAR` ou `VARCHAR` |
| número | Pode ser textual ou numérico, conforme a natureza do dado |
| percentual | Normalmente numérico com precisão e escala variáveis |
| quantidade | Normalmente numérico inteiro ou decimal |
| sigla | Normalmente textual curto |
| texto | Normalmente textual, inclusive com possibilidade de `TEXT` |
| valor | Normalmente numérico, inclusive com precisão decimal |

## Fonte

As regras deste documento foram consolidadas a partir do arquivo `padrao_governanca.csv` presente neste mesmo diretório.