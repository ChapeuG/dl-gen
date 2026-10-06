"""Heurística determinística de padrão de nomenclatura (fallback sem LLM).

Traduz tokens do nome original com um glossário EN→PT, escolhe a natureza pelo
tipo e por palavras-chave e monta natureza_termo_qualificadores. Também usada
pelo agente de nomenclatura para reparar campos que o LLM não acertou.
"""

from __future__ import annotations

import re

from framework.standards.nomenclatura import NATUREZAS, RESERVED_STAGING
from framework.utils import split_tokens

# Expressões compostas (avaliadas antes das palavras isoladas)
PHRASES: dict[tuple[str, ...], list[str]] = {
    ("trade", "name"): ["nome", "fantasia"],
    ("legal", "name"): ["razao", "social"],
    ("company", "name"): ["razao", "social"],
    ("first", "name"): ["nome", "primeiro"],
    ("last", "name"): ["nome", "sobrenome"],
    ("full", "name"): ["nome", "completo"],
    ("zip", "code"): ["cep"],
    ("postal", "code"): ["cep"],
    ("birth", "date"): ["data", "nascimento"],
    ("due", "date"): ["data", "vencimento"],
    ("phone", "number"): ["telefone"],
}

GLOSSARY: dict[str, str] = {
    # identificação
    "id": "id", "identifier": "identificador", "uuid": "id", "code": "codigo", "cod": "codigo",
    "name": "nome", "description": "descricao", "desc": "descricao", "key": "chave",
    "number": "numero", "num": "numero", "nbr": "numero", "no": "numero", "acronym": "sigla", "abbreviation": "sigla",
    # tempo / eventos
    "created": "criacao", "creation": "criacao", "create": "criacao",
    "updated": "atualizacao", "update": "atualizacao", "modified": "alteracao", "changed": "alteracao",
    "deleted": "exclusao", "removed": "exclusao", "inserted": "inclusao", "insert": "inclusao",
    "date": "data", "time": "hora", "timestamp": "datahora", "datetime": "datahora",
    "day": "dia", "month": "mes", "year": "ano", "hour": "hora",
    "start": "inicio", "begin": "inicio", "end": "fim", "finish": "fim",
    "expiration": "expiracao", "expires": "expiracao", "expiry": "expiracao", "due": "vencimento",
    "birth": "nascimento", "reference": "referencia", "ref": "referencia",
    "processing": "processamento", "processed": "processamento", "approved": "aprovacao", "approval": "aprovacao",
    "cancel": "cancelamento", "cancelled": "cancelamento", "canceled": "cancelamento",
    "settlement": "liquidacao", "refund": "estorno", "request": "solicitacao", "response": "resposta",
    # classificação
    "status": "status", "state": "estado", "type": "tipo", "kind": "tipo", "category": "categoria",
    "class": "classe", "level": "nivel", "version": "versao", "channel": "canal", "segment": "segmento",
    "region": "regiao", "role": "perfil", "group": "grupo", "brand": "bandeira",
    # entidades
    "parent": "pai", "child": "filho", "owner": "proprietario", "user": "usuario", "customer": "cliente",
    "client": "cliente", "person": "pessoa", "company": "empresa", "organization": "organizacao",
    "org": "organizacao", "account": "conta", "card": "cartao", "holder": "portador",
    "merchant": "estabelecimento", "store": "loja", "issuer": "emissor", "acquirer": "credenciadora",
    "bank": "banco", "branch": "agencia", "product": "produto", "variant": "variante", "plan": "plano",
    "order": "pedido", "payment": "pagamento", "transaction": "transacao", "transfer": "transferencia",
    "invoice": "fatura", "bill": "fatura", "contract": "contrato", "agreement": "acordo",
    "device": "dispositivo", "network": "rede", "team": "equipe", "record": "registro", "register": "registro",
    # valores e medidas
    "amount": "valor", "value": "valor", "price": "preco", "total": "total", "balance": "saldo",
    "limit": "limite", "fee": "tarifa", "tax": "imposto", "rate": "taxa", "interest": "juros",
    "installment": "parcela", "installments": "parcela", "currency": "moeda",
    "quantity": "quantidade", "qty": "quantidade", "count": "quantidade",
    "percent": "percentual", "percentage": "percentual", "pct": "percentual",
    "size": "tamanho", "weight": "peso", "score": "pontuacao", "rank": "classificacao",
    "forecast": "previsao", "prediction": "previsao", "predicted": "predito",
    # contato / endereço
    "country": "pais", "city": "cidade", "address": "endereco", "street": "logradouro",
    "zip": "cep", "zipcode": "cep", "phone": "telefone", "mobile": "celular", "email": "email", "mail": "email",
    "document": "documento", "doc": "documento", "delivery": "entrega", "shipping": "envio",
    # qualificadores
    "external": "externo", "internal": "interno", "source": "origem", "origin": "origem",
    "target": "destino", "destination": "destino", "active": "ativo", "enabled": "habilitado",
    "disabled": "desabilitado", "blocked": "bloqueado", "valid": "valido", "default": "padrao",
    "primary": "principal", "main": "principal", "last": "ultimo", "first": "primeiro",
    "current": "atual", "previous": "anterior", "next": "proximo", "new": "novo", "old": "antigo",
    "trade": "comercial", "legal": "legal", "view": "visao", "final": "final",
    # textos
    "message": "mensagem", "reason": "motivo", "error": "erro", "note": "observacao", "notes": "observacao",
    "comment": "comentario", "title": "titulo", "label": "rotulo", "file": "arquivo", "path": "caminho",
    "password": "senha", "secret": "segredo", "flag": "indicador",
}

STOPWORDS = {"at", "of", "the", "on", "by", "to", "a", "an", "is", "has", "was", "de", "do", "da", "dos", "das", "e"}

# Palavra (PT) → natureza
NAT_KEYWORDS: dict[str, str] = {
    "nome": "nm", "descricao": "dc", "observacao": "dc", "mensagem": "dc",
    "valor": "vl", "preco": "vl", "saldo": "vl", "tarifa": "vl", "limite": "vl",
    "quantidade": "qt", "percentual": "pc",
    "numero": "nu", "documento": "nu", "telefone": "nu", "celular": "nu", "cep": "nu", "cpf": "nu", "cnpj": "nu",
    "codigo": "cd", "status": "cd", "tipo": "cd", "categoria": "cd", "estado": "cd",
    "id": "id", "identificador": "id",
    "ano": "aa", "mes": "mm", "dia": "dd", "hora": "hr", "sigla": "sg", "indicador": "in",
}

# Palavras que só indicam a natureza — saem do nome quando há outros termos (trade_name → nm_fantasia)
NAT_ONLY_WORDS = {"nome", "descricao", "valor", "quantidade", "percentual", "numero", "codigo",
                  "id", "identificador", "indicador", "sigla", "data", "datahora"}

# Acentuação para os comentários gerados
ACCENTS: dict[str, str] = {
    "criacao": "criação", "atualizacao": "atualização", "alteracao": "alteração", "exclusao": "exclusão",
    "inclusao": "inclusão", "situacao": "situação", "descricao": "descrição", "organizacao": "organização",
    "endereco": "endereço", "cartao": "cartão", "numero": "número", "codigo": "código",
    "referencia": "referência", "transacao": "transação", "visao": "visão", "mes": "mês",
    "usuario": "usuário", "pais": "país", "agencia": "agência", "razao": "razão", "operacao": "operação",
    "versao": "versão", "ultimo": "último", "padrao": "padrão", "periodo": "período", "horario": "horário",
    "previsao": "previsão", "expiracao": "expiração", "aprovacao": "aprovação", "liquidacao": "liquidação",
    "solicitacao": "solicitação", "transferencia": "transferência", "proprietario": "proprietário",
    "regiao": "região", "nivel": "nível", "valido": "válido", "proximo": "próximo", "pontuacao": "pontuação",
    "classificacao": "classificação", "comentario": "comentário", "titulo": "título", "rotulo": "rótulo",
    "observacao": "observação", "credito": "crédito", "debito": "débito", "emissao": "emissão",
}


def translate_tokens(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Traduz tokens EN→PT. Retorna (tokens_pt, tokens_sem_traducao)."""
    out: list[str] = []
    unknown: list[str] = []
    i = 0
    while i < len(tokens):
        pair = tuple(tokens[i:i + 2])
        if len(pair) == 2 and pair in PHRASES:
            out.extend(PHRASES[pair])
            i += 2
            continue
        tok = tokens[i]
        i += 1
        if tok in STOPWORDS:
            continue
        if tok in GLOSSARY:
            out.append(GLOSSARY[tok])
        else:
            out.append(tok)
            if not tok.isdigit() and tok not in GLOSSARY.values() and tok not in NAT_KEYWORDS:
                unknown.append(tok)
    return out, unknown


def _varchar_length(raw_type: str) -> int | None:
    m = re.search(r"\((\d+)\)", raw_type)
    return int(m.group(1)) if m else None


def _default_natureza(field: dict) -> str:
    raw_type = (field.get("raw_type") or "").lower()
    dt = field["data_type"]
    if raw_type.startswith("uuid"):
        return "id"
    if dt == "BooleanType":
        return "in"
    if dt in ("IntegerType", "LongType"):
        return "cd"
    if dt in ("DoubleType", "FloatType") or dt.startswith("DecimalType"):
        return "vl"
    length = _varchar_length(raw_type)
    if raw_type.startswith("char") or (length is not None and length <= 50):
        return "cd"
    return "dc"


def _pick_natureza(field: dict, terms: list[str]) -> tuple[str, str | None]:
    """Retorna (natureza, palavra que a definiu ou None)."""
    dt = field["data_type"]
    if dt == "TimestampType":
        return "dh", None
    if dt == "DateType":
        return "dt", None
    if dt == "BooleanType":
        return "in", None
    # Prioridade: último termo (trade_name, parent_id), depois o primeiro (tipo_pessoa), depois qualquer
    candidates = [terms[-1], terms[0], *terms] if terms else []
    for t in candidates:
        if t in NAT_KEYWORDS:
            return NAT_KEYWORDS[t], t
    return _default_natureza(field), None


def make_comment(nat: str, terms: list[str], table_name: str) -> str:
    pretty = " ".join(ACCENTS.get(t, t) for t in terms)
    table_pretty = " ".join(ACCENTS.get(t, t) for t in translate_tokens(split_tokens(table_name))[0])
    label = NATUREZAS[nat]
    if not pretty or pretty.lower() == label.lower():
        return f"{label} do registro de {table_pretty}."
    return f"{label} de {pretty}."


def propose_field(field: dict, table_name: str) -> tuple[str, str, list[str]]:
    """Propõe (staging_field, comment, tokens_sem_traducao) para um campo."""
    tokens = split_tokens(field["raw_field"])

    # Já vem no padrão (cd_credenciadora, nm_produto...) — mantém a natureza
    if len(tokens) > 1 and tokens[0] in NATUREZAS:
        nat = tokens[0]
        terms, unknown = translate_tokens(tokens[1:])
    else:
        terms, unknown = translate_tokens(tokens)
        nat, keyword = _pick_natureza(field, terms)
        removable = [t for t in terms if t in NAT_ONLY_WORDS and (t == keyword or nat in ("dt", "dh"))]
        if removable and len(terms) > len(removable):
            terms = [t for t in terms if t not in removable]
        elif terms and set(terms) <= {"id", "identificador", "codigo"}:
            terms = []  # id / code sozinhos → identificador da própria tabela (id_organizacao)

    if not terms:
        terms, _ = translate_tokens(split_tokens(table_name))

    staging = "_".join([nat, *terms])
    if staging in RESERVED_STAGING:
        staging += "_origem"

    comment = field.get("comment") or make_comment(nat, terms, table_name)
    return staging, comment, unknown
