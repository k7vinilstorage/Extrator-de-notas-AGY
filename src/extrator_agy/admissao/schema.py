"""Campos de cada documento e do texto, e os JSON Schemas enviados ao agy.

Como em schema.py, todos os campos são obrigatórios e anuláveis: o modelo
responde cada um, com null quando não aparece. O agy transcreve como impresso
ou escrito; o formato ao lado de cada campo (ver regras.FORMATOS) diz como o
código converte e confere o valor.
"""

STR = {"type": ["string", "null"]}

# tipo → campo → formato
CAMPOS_DOCUMENTO = {
    "rg": {
        "numero": "maiusculo", "orgao_emissor": "maiusculo", "uf_emissor": "uf", "data_expedicao": "data",
        "cpf": "cpf", "data_nascimento": "data", "sexo": "sexo", "nome_mae": "nome", "nome_pai": "nome",
        "naturalidade": "maiusculo", "uf_naturalidade": "uf", "nacionalidade": "maiusculo",
    },
    "cnh": {
        "numero_registro": "cnh", "categoria": "categoria_cnh", "uf_emissor": "uf", "data_emissao": "data",
        "data_primeira_habilitacao": "data", "validade": "data_futura", "cpf": "cpf", "data_nascimento": "data",
        "local_nascimento": "maiusculo", "uf_nascimento": "uf", "nome_mae": "nome", "nome_pai": "nome",
        "rg_numero": "maiusculo", "rg_orgao_emissor": "maiusculo", "rg_uf": "uf",
    },
    "cpf": {"cpf": "cpf", "data_nascimento": "data"},
    "ctps_digital": {
        "cpf": "cpf", "data_nascimento": "data", "sexo": "sexo", "nacionalidade": "maiusculo",
        "nome_mae": "nome", "nome_pai": "nome", "numero": "maiusculo", "serie": "maiusculo", "uf": "uf",
        "pis": "pis",
    },
    "titulo_eleitor": {
        "numero": "titulo", "zona": "zona_secao", "secao": "zona_secao", "municipio": "maiusculo", "uf": "uf",
        "data_emissao": "data", "data_nascimento": "data", "nome_mae": "nome", "nome_pai": "nome",
    },
    "comprovante_residencia": {
        "titular": "nome", "logradouro": "maiusculo", "numero": "maiusculo", "complemento": "maiusculo",
        "bairro": "maiusculo", "municipio": "maiusculo", "uf": "uf", "cep": "cep", "data_referencia": "data",
    },
    "certidao_nascimento": {
        "matricula": "matricula", "data_nascimento": "data", "sexo": "sexo", "municipio_nascimento": "maiusculo",
        "uf_nascimento": "uf", "nome_pai": "nome", "nome_mae": "nome", "cpf": "cpf", "data_registro": "data",
        "cartorio": "maiusculo", "livro": "maiusculo", "folha": "maiusculo", "termo": "maiusculo",
        "anotacoes": "texto",
    },
    "certidao_casamento": {
        "matricula": "matricula", "conjuge_1": "nome", "conjuge_1_nome_apos_casamento": "nome",
        "conjuge_1_cpf": "cpf", "conjuge_1_data_nascimento": "data", "conjuge_2": "nome",
        "conjuge_2_nome_apos_casamento": "nome", "conjuge_2_cpf": "cpf", "conjuge_2_data_nascimento": "data",
        "data_casamento": "data", "regime_bens": "maiusculo", "averbacoes": "texto", "cartorio": "maiusculo",
    },
    "comprovante_escolaridade": {
        "instituicao": "maiusculo", "nivel": "texto", "curso": "maiusculo", "situacao": "texto",
        "data_conclusao": "data",
    },
    "comprovante_pis": {"pis": "pis"},
    "dados_bancarios": {
        "titular": "nome", "banco": "maiusculo", "agencia": "maiusculo", "conta": "maiusculo",
        "tipo_conta": "texto",
    },
}

TIPOS = [*CAMPOS_DOCUMENTO, "outro"]

DESCRICAO_TIPOS = {
    "rg": "RG estadual ou CIN (Carteira de Identidade Nacional)",
    "cnh": "CNH, física ou digital",
    "cpf": "cartão do CPF ou comprovante de situação cadastral",
    "ctps_digital": "Carteira de Trabalho Digital",
    "titulo_eleitor": "título de eleitor ou e-Título",
    "comprovante_residencia": "conta de luz, água, telefone, internet, banco ou contrato de aluguel",
    "certidao_nascimento": "certidão de nascimento",
    "certidao_casamento": "certidão de casamento",
    "comprovante_escolaridade": "diploma, certificado, histórico ou declaração escolar",
    "comprovante_pis": "Cartão Cidadão, extrato do PIS/FGTS ou CNIS",
    "dados_bancarios": "cartão, extrato ou comprovante de conta bancária",
    "outro": "qualquer outro documento",
}


def _objeto(propriedades: dict, anulavel: bool = False) -> dict:
    return {
        "type": ["object", "null"] if anulavel else "object",
        "additionalProperties": False,
        "properties": propriedades,
        "required": list(propriedades),
    }


DOCUMENTO = _objeto({
    "tipo": {"type": "string", "enum": TIPOS},
    "nome": STR,
    **{tipo: _objeto({campo: STR for campo in campos}, anulavel=True) for tipo, campos in CAMPOS_DOCUMENTO.items()},
})

DOCUMENTOS = _objeto({"documentos": {"type": "array", "items": DOCUMENTO}})

# Caminho na ficha → formato. Do texto saem os dados do contrato e o que o
# funcionário declara e costuma não estar em documento.
CAMPOS_TEXTO = {
    "funcionario.nome": "nome",
    "funcionario.sexo": "sexo",
    "funcionario.estado_civil": "estado_civil",
    "funcionario.raca_cor": "raca_cor",
    "funcionario.grau_instrucao": "grau_instrucao",
    "funcionario.nacionalidade": "maiusculo",
    "funcionario.pais_nascimento": "maiusculo",
    "funcionario.pis": "pis",
    "funcionario.telefone": "telefone",
    "funcionario.email": "email",
    "funcionario.deficiencia": "texto",
    "funcionario.endereco.logradouro": "maiusculo",
    "funcionario.endereco.numero": "maiusculo",
    "funcionario.endereco.complemento": "maiusculo",
    "funcionario.endereco.bairro": "maiusculo",
    "funcionario.endereco.municipio": "maiusculo",
    "funcionario.endereco.uf": "uf",
    "funcionario.endereco.cep": "cep",
    "funcionario.banco.banco": "maiusculo",
    "funcionario.banco.agencia": "maiusculo",
    "funcionario.banco.conta": "maiusculo",
    "funcionario.banco.tipo_conta": "texto",
    "funcionario.banco.pix": "texto",
    "contrato.data_admissao": "data_futura",
    "contrato.cargo": "maiusculo",
    "contrato.funcao": "maiusculo",
    "contrato.cbo": "cbo",
    "contrato.salario": "dinheiro",
    "contrato.tipo_salario": "tipo_salario",
    "contrato.tipo_contrato": "tipo_contrato",
    "contrato.experiencia.dias": "inteiro",
    "contrato.experiencia.prorrogacao_dias": "inteiro",
    "contrato.data_termino": "data_futura",
    "contrato.horario.entrada": "hora",
    "contrato.horario.saida": "hora",
    "contrato.horario.intervalo_inicio": "hora",
    "contrato.horario.intervalo_fim": "hora",
    "contrato.horario.intervalo_minutos": "duracao",
    "contrato.horario.dias": "texto",
    "contrato.escala": "escala",
    "contrato.jornada_semanal_horas": "numero",
    "contrato.local_trabalho": "maiusculo",
    "contrato.departamento": "maiusculo",
    "contrato.sindicato": "maiusculo",
    "contrato.vale_transporte": "sim_nao",
    "contrato.aso.data": "data",
    "contrato.aso.apto": "sim_nao",
    "contrato.primeiro_emprego": "sim_nao",
}

CAMPOS_DEPENDENTE_TEXTO = {
    "nome": "nome", "parentesco": "parentesco", "irrf": "sim_nao", "salario_familia": "sim_nao",
}

# Cada campo do texto vem com o trecho de onde saiu, para quem revisa encontrar.
CITADO = _objeto({"valor": STR, "trecho": STR}, anulavel=True)


def _aninhar(caminhos: list[str]) -> dict:
    arvore: dict = {}
    for caminho in caminhos:
        *grupos, folha = caminho.split(".")
        no = arvore
        for grupo in grupos:
            no = no.setdefault(grupo, {})
        no[folha] = None
    return arvore


def _schema_arvore(arvore: dict) -> dict:
    return _objeto({k: CITADO if v is None else _schema_arvore(v) for k, v in arvore.items()})


TEXTO = _schema_arvore(_aninhar(list(CAMPOS_TEXTO)))
TEXTO["properties"]["contrato"]["properties"]["beneficios"] = {"type": ["array", "null"], "items": CITADO}
TEXTO["properties"]["contrato"]["required"].append("beneficios")
TEXTO["properties"]["dependentes"] = {
    "type": ["array", "null"],
    "items": _objeto({**{campo: STR for campo in CAMPOS_DEPENDENTE_TEXTO}, "trecho": STR}),
}
TEXTO["properties"]["outras_informacoes"] = {"type": ["array", "null"], "items": {"type": "string"}}
TEXTO["required"] += ["dependentes", "outras_informacoes"]
