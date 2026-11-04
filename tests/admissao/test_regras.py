from datetime import date, timedelta

import pytest

from extrator_agy.admissao import regras
from numeros import cpf, pis, titulo, trocar_ultimo


def test_pis():
    assert regras.pis_valido(pis())
    assert not regras.pis_valido(trocar_ultimo(pis()))
    assert not regras.pis_valido("111.11111.11-1")
    assert not regras.pis_valido("1234")


def test_titulo():
    # Exemplo público de SC (UF 09) com DV conhecido.
    assert regras.titulo_valido("0043 5687 0906")
    assert regras.titulo_valido(titulo())
    assert regras.titulo_valido(titulo("87654321", "01"))
    assert not regras.titulo_valido(trocar_ultimo(titulo()))
    assert not regras.titulo_valido("0043 5687 2906")  # UF 29 não existe
    assert regras.uf_do_titulo(titulo(uf="02")) == "MG"


def test_titulo_de_13_digitos_confere_so_a_uf():
    assert regras.titulo_valido("123456789" + "01" + "99")
    assert not regras.titulo_valido("123456789" + "29" + "99")


@pytest.mark.parametrize("cep,uf", [
    ("01001-000", "SP"), ("19999999", "SP"), ("20000000", "RJ"), ("69300-000", "RR"), ("69400-000", "AM"),
    ("70000000", "DF"), ("72800000", "GO"), ("88010-000", "SC"), ("99999999", "RS"), ("00500000", None), ("123", None),
])
def test_uf_do_cep(cep, uf):
    assert regras.uf_do_cep(cep) == uf


@pytest.mark.parametrize("texto,valor", [
    ("R$ 2.500,00", 2500.0), ("2500", 2500.0), ("2.500", 2500.0), ("2500,00", 2500.0), ("2500.00", 2500.0),
    ("r$1.234.567,8", 1234567.8), ("R$ 1.518,00.", 1518.0),
    ("2,5 mil", None), ("dois mil", None), ("piso da categoria", None), ("", None), (None, None),
])
def test_dinheiro(texto, valor):
    assert regras.dinheiro(texto) == valor


@pytest.mark.parametrize("texto,valor", [
    ("8h", "08:00"), ("08:30", "08:30"), ("8h30", "08:30"), ("17:00", "17:00"), ("12h00min", "12:00"),
    ("25h", None), ("8h70", None), ("de manhã", None),
])
def test_hora(texto, valor):
    assert regras.hora(texto) == valor


@pytest.mark.parametrize("texto,valor", [
    ("1h", 60), ("1h30", 90), ("1:15", 75), ("90 min", 90), ("60 minutos", 60), ("2 horas", 120), ("uma hora", None),
])
def test_duracao(texto, valor):
    assert regras.duracao_minutos(texto) == valor


@pytest.mark.parametrize("texto,valor", [
    ("45", 45), ("45 dias", 45), ("mais 60", 60), ("+ 45 dias", 45), ("prorrogáveis por mais 60 dias", 60),
    ("45 + 45", None), ("quarenta e cinco", None), ("60 ou 90", None),
])
def test_inteiro(texto, valor):
    assert regras.inteiro(texto) == valor


def test_chave_nome():
    assert regras.chave_nome("Maria  da Conceição DOS Santos") == "MARIA CONCEICAO SANTOS"
    assert regras.chave_nome("MARIA CONCEICAO SANTOS") == regras.chave_nome("maria da conceição dos santos")


@pytest.mark.parametrize("texto,grau", [
    ("Certificado de conclusão do Ensino Médio", "medio_completo"),
    ("2º grau completo", "medio_completo"),
    ("cursando o ensino médio", "medio_incompleto"),
    ("Bacharel em Administração", "superior_completo"),
    ("Graduação em Direito - trancado", "superior_incompleto"),
    ("Diploma de Mestrado", "mestrado"),
    ("Especialização (MBA) concluída", "pos_graduacao"),
    ("Mestrado em andamento", "superior_completo"),
    ("Ensino fundamental completo", "fundamental_completo"),
    ("fundamental incompleto", None),  # não diz até que ano
    ("Ensino médio", None),  # não diz se concluiu
    ("Curso de Excel", None),
])
def test_grau_instrucao(texto, grau):
    assert regras.grau_instrucao(texto) == grau


@pytest.mark.parametrize("formato,valor,esperado", [
    ("cpf", cpf(), cpf()),
    ("cpf", "12345678909", "123.456.789-09"),
    ("pis", pis().replace(".", "").replace("-", ""), pis()),
    ("data", "05/03/1990", "1990-03-05"),
    ("data", "05 / 03 / 1990", "1990-03-05"),
    ("data", "05.03.1990", "1990-03-05"),
    ("uf", " sp ", "SP"),
    ("cep", "88.010-000", "88010-000"),
    ("telefone", "(11) 99999-0000", "11999990000"),
    ("telefone", "+55 48 3333-4444", "4833334444"),
    ("estado_civil", "Casada", "casado"),
    ("estado_civil", "vive em união estável", "uniao_estavel"),
    ("raca_cor", "Parda", "parda"),
    ("raca_cor", "prefere não informar", "nao_informado"),
    ("sexo", "Feminino", "F"),
    ("sim_nao", "não", False),
    ("sim_nao", "Sim", True),
    ("tipo_contrato", "prazo indeterminado", "indeterminado"),
    ("tipo_contrato", "45 dias de experiência", "experiencia"),
    ("categoria_cnh", "A B", "AB"),
    ("escala", "12 x 36", "12x36"),
    ("nome", "  maria   exemplo ", "MARIA EXEMPLO"),
    ("cpf", None, None),
    ("cpf", "  ", None),
])
def test_normalizar(formato, valor, esperado):
    assert regras.normalizar(formato, valor) == (esperado, None)


@pytest.mark.parametrize("formato,valor,trecho", [
    ("cpf", trocar_ultimo(cpf()), "dígito verificador"),
    ("cpf", "1234", "11 dígitos"),
    ("data", "31/02/1990", "data inválida"),
    ("data", (date.today() + timedelta(days=5)).isoformat(), "futuro"),
    ("telefone", "(10) 99999-0000", "DDD"),
    ("raca_cor", "negra", "não reconhecido"),  # no IBGE junta preta e parda
    ("titulo", trocar_ultimo(titulo()), "título"),
    ("matricula", "123", "matrícula"),
])
def test_normalizar_com_problema(formato, valor, trecho):
    convertido, problema = regras.normalizar(formato, valor)
    assert convertido is None and trecho in problema
    # O problema vai para o prompt da releitura: não pode conter o valor lido.
    assert str(valor) not in problema


def test_data_futura_aceita_o_futuro():
    amanha = (date.today() + timedelta(days=1)).isoformat()
    assert regras.normalizar("data_futura", amanha) == (amanha, None)


def test_idade():
    assert regras.idade("2000-06-15", "2026-06-14") == 25
    assert regras.idade("2000-06-15", "2026-06-15") == 26


@pytest.mark.parametrize("a,b,esperado", [
    ("MARIA E. DA SILVA", "Maria Exemplo da Silva", True),
    ("MARIA J SILVA", "MARIA JOSE SILVA", True),
    ("MARIA SILVA", "MARIA JOSE SILVA", False),  # nome do meio omitido não é abreviação
    ("M. JOSE SILVA", "MARIA JOSE SILVA", False),  # primeiro nome tem de estar por extenso
    ("MARIA JOSE SILVA", "MARIA JOANA SILVA", False),
])
def test_abreviacao(a, b, esperado):
    assert regras.abreviacao(a, b) is esperado


@pytest.mark.parametrize("a,b,esperado", [
    ("MARIA E. DA SILVA", "MARIA EXEMPLO DA SILVA", True),
    ("MARIA SILVA", "MARIA JOSE DA SILVA", True),
    ("ANA SILVA", "MARIA SILVA", False),
    ("MARIA SILVA", "MARIA SOUZA", False),
    ("MARIA JOSE SILVA", "MARIA SILVA JOSE", False),
    (None, "MARIA SILVA", False),
])
def test_mesma_pessoa(a, b, esperado):
    assert regras.mesma_pessoa(a, b) is esperado


def test_nome_mais_completo():
    assert regras.nome_mais_completo(["MARIA E. DA SILVA", "MARIA EXEMPLO DA SILVA"]) == "MARIA EXEMPLO DA SILVA"


@pytest.mark.parametrize("texto,esperado", [
    ("24 DE JUNHO DE 1998", "1998-06-24"), ("1º de maio de 2000", "2000-05-01"), ("24/JUN/1998", "1998-06-24"),
    ("07 de Dezembro de 2026", "2026-12-07"), ("7 de março de 1985", "1985-03-07"),
])
def test_data_com_mes_por_extenso(texto, esperado):
    assert regras.normalizar("data_futura", texto) == (esperado, None)


def test_data_com_mes_desconhecido():
    assert regras.normalizar("data", "24 de junhoo de 1998")[0] is None


@pytest.mark.parametrize("texto", ["Feminina", "FEMININO", "F"])
def test_sexo_feminino(texto):
    assert regras.normalizar("sexo", texto) == ("F", None)


def test_mesma_pessoa_com_particula_abreviada():
    assert regras.mesma_pessoa("MARIA E. D. SILVA", "MARIA EXEMPLO DA SILVA")
    assert regras.mesma_pessoa("MARIA E. SILVA", "MARIA EXEMPLO SILVA")  # E. pode ser "EXEMPLO"


@pytest.mark.parametrize("texto,uf", [("AMAZONAS", "AM"), ("São Paulo", "SP"), ("Estado do Rio de Janeiro", "RJ"),
                                      ("mato grosso do sul", "MS"), ("Mato Grosso", "MT"), ("sc", "SC")])
def test_uf_por_extenso(texto, uf):
    assert regras.normalizar("uf", texto) == (uf, None)


@pytest.mark.parametrize("texto,esperado", [
    ("BRASILEIRO", "BRASILEIRA"), ("brasileira", "BRASILEIRA"), ("Brasil", "BRASILEIRA"),
    ("BRASILEIRO(A)", "BRASILEIRA"), ("brasileira nata", "BRASILEIRA"), ("italiano", "ITALIANO"),
])
def test_nacionalidade(texto, esperado):
    assert regras.normalizar("nacionalidade", texto) == (esperado, None)


def test_cnpj():
    assert regras.normalizar("cnpj", "11222333000181") == ("11.222.333/0001-81", None)
    assert "dígito verificador" in regras.normalizar("cnpj", "11.222.333/0001-82")[1]
