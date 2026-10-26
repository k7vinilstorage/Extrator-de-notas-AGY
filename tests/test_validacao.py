import pytest

from extrator_agy.validacao import (
    chave_valida, cnpj_valido, cpf_valido, data_iso, decompor_chave, dv_chave, normalizar, validar,
)

CHAVE = "42260204140144000102650020004252171271619150"

NOTA = {
    "cpf_cnpj": "04.140.144/0001-02",
    "razao_social": "POSTO Z1 LTDA",
    "uf": "SC",
    "municipio": "JOINVILLE",
    "numero_nota": "425217",
    "data_emissao": "2026-02-27",
    "valor_total": 100.0,
    "chave_acesso": CHAVE,
    "categoria_gasto": "combustivel",
    "itens": None,
}

# NFS-e do padrão nacional, pública no portal nfse.gov.br
CHAVE_NFSE = "53001082247550802000139000000000001124072903992230"

NFSE = {
    "cpf_cnpj": "47.550.802/0001-39",
    "razao_social": None,
    "uf": "DF",
    "municipio": "BRASILIA",
    "numero_nota": "11",
    "data_emissao": "2024-07-10",
    "valor_total": None,
    "chave_acesso": CHAVE_NFSE,
    "categoria_gasto": "servicos",
    "itens": None,
}

# NF-e (modelo 55) real de combustível
CHAVE_NFE = "33260931665558000110550120000433001005399770"

NFE = {
    "cpf_cnpj": "31.665.558/0001-10",
    "razao_social": "AUTO POSTO JARDIM PRIMAVERA LTDA",
    "uf": "RJ",
    "municipio": "DUQUE DE CAXIAS",
    "numero_nota": "43300",
    "data_emissao": "2026-09-02",
    "valor_total": 465.51,
    "chave_acesso": CHAVE_NFE,
    "categoria_gasto": "combustivel",
    "itens": [{"descricao": "DIESEL B S10", "ncm": "27101921"}],
}


def test_nota_real_valida():
    assert validar(NOTA) == []


def test_decompor_chave():
    assert decompor_chave(CHAVE) == {
        "uf": "42", "aamm": "2602", "cpf_cnpj": "04140144000102", "modelo": "65", "numero": "000425217",
    }
    assert dv_chave(CHAVE[:43]) == 0


@pytest.mark.parametrize("campo,valor,trecho", [
    ("chave_acesso", CHAVE[:-1] + "3", "dígito verificador"),
    ("chave_acesso", CHAVE + "12", "46 caracteres"),
    ("numero_nota", "425211", "número da nota"),
    ("data_emissao", "2026-03-27", "ano/mês"),
    ("data_emissao", "2026-02-30", "data de emissão inválida"),
    ("uf", "PR", "UF"),
    ("cpf_cnpj", "04.140.144/0001-03", "CPF/CNPJ inválido"),
])
def test_divergencias(campo, valor, trecho):
    problemas = validar(NOTA | {campo: valor})
    assert any(trecho in p for p in problemas), problemas


def test_nfse_valida():
    assert validar(NFSE) == []
    assert decompor_chave(CHAVE_NFSE) == {
        "uf": "53", "aamm": "2407", "cpf_cnpj": "47550802000139", "modelo": "nfse", "numero": "0000000000011",
    }


@pytest.mark.parametrize("campo,valor,trecho", [
    ("chave_acesso", CHAVE_NFSE[:-1] + "1", "dígito verificador"),
    ("numero_nota", "12", "número da nota"),
    ("data_emissao", "2024-08-10", "ano/mês"),
    ("uf", "GO", "UF"),
    ("cpf_cnpj", "11.222.333/0001-81", "difere do da chave"),
])
def test_divergencias_nfse(campo, valor, trecho):
    problemas = validar(NFSE | {campo: valor})
    assert any(trecho in p for p in problemas), problemas


def test_normalizar_completa_pela_chave_da_nfse():
    n = normalizar(NFSE | {"cpf_cnpj": None, "uf": None, "numero_nota": None})
    assert (n["cpf_cnpj"], n["uf"], n["numero_nota"]) == ("47.550.802/0001-39", "DF", "11")


@pytest.mark.parametrize("texto,esperado", [
    ("2026-09-24T10:06:00", "2026-09-24"),
    ("2026-09-24", "2026-09-24"),
    ("24/09/2026 10:06", "2026-09-24"),
    ("2026-02-30", None),
    ("ontem", None),
    (None, None),
])
def test_data_iso(texto, esperado):
    assert data_iso(texto) == esperado


def test_normalizar_tira_a_hora_da_data():
    assert normalizar(NOTA | {"data_emissao": "2026-02-27T16:19:15"})["data_emissao"] == "2026-02-27"
    assert normalizar(NOTA | {"data_emissao": "sem data"})["data_emissao"] == "sem data"


def test_cnpj_valido_mas_diferente_da_chave():
    problemas = validar(NOTA | {"cpf_cnpj": "11.222.333/0001-81"})
    assert any("difere do da chave" in p for p in problemas)


def test_normalizar_padroniza_formatos():
    n = normalizar(NOTA | {"cpf_cnpj": "04140144000102", "numero_nota": "000425217",
                           "municipio": "Joinville ", "uf": "sc", "chave_acesso": "4226 0204 " + CHAVE[8:]})
    assert n["cpf_cnpj"] == "04.140.144/0001-02"
    assert n["numero_nota"] == "425217"
    assert (n["municipio"], n["uf"]) == ("JOINVILLE", "SC")
    assert n["chave_acesso"] == CHAVE


def test_normalizar_completa_pela_chave():
    n = normalizar(NOTA | {"cpf_cnpj": None, "uf": None, "numero_nota": None})
    assert (n["cpf_cnpj"], n["uf"], n["numero_nota"]) == ("04.140.144/0001-02", "SC", "425217")


def test_sem_chave():
    assert validar(NOTA | {"chave_acesso": None}) == []


def test_cnpj_cpf_e_chave():
    assert cnpj_valido("04.140.144/0001-02")
    assert not cnpj_valido("11.111.111/1111-11")
    # Exemplo de CNPJ alfanumérico publicado pela Receita Federal
    assert cnpj_valido("12.ABC.345/01DE-35")
    assert cpf_valido("529.982.247-25")
    assert not cpf_valido("529.982.247-26")
    assert chave_valida(CHAVE) and not chave_valida(CHAVE[:-1] + "1")
    assert chave_valida(CHAVE_NFSE) and not chave_valida(CHAVE_NFSE[:44])
    assert chave_valida(CHAVE_NFE) and not chave_valida(CHAVE_NFE[:-1] + "1")


def test_nfe_valida():
    assert decompor_chave(CHAVE)["modelo"] == "65"
    assert decompor_chave(CHAVE_NFE) == {
        "uf": "33", "aamm": "2609", "cpf_cnpj": "31665558000110", "modelo": "55", "numero": "000043300",
    }
    assert validar(NFE) == []


def test_normalizar_ncm_e_itens():
    n = normalizar({"itens": [{"descricao": " DIESEL B S10 ", "ncm": "2710.19.21"}]})
    assert n["itens"] == [{"descricao": "DIESEL B S10", "ncm": "27101921"}]
    assert normalizar({"itens": []})["itens"] is None
    assert normalizar({"itens": None})["itens"] is None
    assert normalizar({})["itens"] is None


def test_ncm_com_7_digitos_acusa():
    problemas = validar(NFE | {"itens": [{"descricao": "DIESEL B S10", "ncm": "1234567"}]})
    assert any("NCM inválido (1234567) no item 1" in p for p in problemas)


def test_nfe_sem_itens_acusa():
    problemas = validar(NFE | {"itens": None})
    assert "itens da NF-e não lidos" in problemas


def test_nfce_sem_itens_nao_acusa():
    assert validar(NOTA) == []


def test_ncm_conferido_mesmo_sem_chave():
    problemas = validar(NFE | {"chave_acesso": None, "itens": [{"descricao": "DIESEL", "ncm": "271019"}]})
    assert problemas == ["NCM inválido (271019) no item 1"]


def test_validacao_ncm_com_texto():
    assert validar(NFE, texto="5 820101034 DIESEL B S10 111,72 27101921 061 5656 L 71,07") == []
    problemas = validar(NFE, texto="DIESEL B S10 sem ncm")
    assert any("NCM 27101921 do item 1 não aparece no texto do PDF" in p for p in problemas)
