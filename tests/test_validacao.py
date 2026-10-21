import pytest

from extrator_agy.validacao import (
    chave_valida, cnpj_valido, cpf_valido, decompor_chave, dv_chave, normalizar, validar,
)

CHAVE = "42260204140144000102650020004252171271619150"

NOTA = {
    "cpf_cnpj": "04.140.144/0001-02",
    "razao_social": "POSTO Z1 LTDA",
    "uf": "SC",
    "municipio": "JOINVILLE",
    "numero_nota": "425217",
    "data_emissao": "2026-02-27T16:19:15",
    "valor_total": 100.0,
    "chave_acesso": CHAVE,
    "categoria_gasto": "combustivel",
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
    ("data_emissao", "2026-03-27T16:19:15", "ano/mês"),
    ("uf", "PR", "UF"),
    ("cpf_cnpj", "04.140.144/0001-03", "CPF/CNPJ inválido"),
])
def test_divergencias(campo, valor, trecho):
    problemas = validar(NOTA | {campo: valor})
    assert any(trecho in p for p in problemas), problemas


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
