"""JSON Schema enviado ao agy via --json-schema.

Só os campos necessários, todos obrigatórios e anuláveis: o modelo precisa
responder cada um explicitamente, usando null quando não aparece no documento.
Quanto menor o schema, menos tokens de saída e mais rápida a extração.
"""

CATEGORIAS = [
    "combustivel",
    "mercado",
    "restaurante_alimentacao",
    "farmacia_saude",
    "transporte",
    "hospedagem",
    "vestuario",
    "eletronicos",
    "casa_construcao",
    "servicos",
    "educacao",
    "lazer",
    "outros",
]

STR = {"type": ["string", "null"]}

ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"descricao": STR, "ncm": STR},
    "required": ["descricao", "ncm"],
}

NOTA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cpf_cnpj": STR,
        "razao_social": STR,
        "uf": STR,
        "municipio": STR,
        "numero_nota": STR,
        "data_emissao": STR,
        "valor_total": {"type": ["number", "null"]},
        "chave_acesso": STR,
        "categoria_gasto": {"type": "string", "enum": CATEGORIAS},
        "itens": {"type": ["array", "null"], "items": ITEM},
    },
}
NOTA["required"] = list(NOTA["properties"])
