"""Campos informados no painel: valem acima das leituras e não passam pelo agy."""

import pytest
from test_ficha import CPF, arq, doc, documentos_completos, texto
from test_fluxo import item

from extrator_agy.admissao import fluxo, informados
from extrator_agy.admissao.ficha import INFORMADO
from extrator_agy.extracao import Config
from numeros import cpf


def lido_do_texto(fonte: dict) -> dict:
    return {"arquivo": "texto", "status": "ok", "fonte": fonte}


def test_ler_converte_pelas_regras_do_texto():
    lidos = informados.ler(
        '{"funcionario.estado_civil": "uniao_estavel", "funcionario.grau_instrucao": "pos_graduacao",'
        ' "funcionario.sexo": "F", "funcionario.raca_cor": "parda", "contrato.salario": "2.500,00",'
        ' "contrato.data_admissao": "16/11/2026", "funcionario.endereco.cep": "80010000",'
        ' "funcionario.endereco.uf": "pr", "contrato.vale_transporte": true, "funcionario.cpf": "' + CPF + '",'
        ' "funcionario.endereco.bairro": "   "}')
    assert lidos == {
        "funcionario.estado_civil": "uniao_estavel", "funcionario.grau_instrucao": "pos_graduacao",
        "funcionario.sexo": "F", "funcionario.raca_cor": "parda", "contrato.salario": 2500.0,
        "contrato.data_admissao": "2026-11-16", "funcionario.endereco.cep": "80010-000",
        "funcionario.endereco.uf": "PR", "contrato.vale_transporte": True, "funcionario.cpf": CPF,
    }, "o valor do enum vale como está; o vazio é ignorado"
    assert informados.ler(None) == informados.ler("  ") == {}


@pytest.mark.parametrize("campos,trecho", [
    ("[1]", "objeto"),
    ("{x", "JSON"),
    ('{"funcionario.nome_mae": "X"}', "não podem ser informados: funcionario.nome_mae"),
    ('{"funcionario.cpf": "11111111111", "funcionario.data_nascimento": "31/02/1990"}',
     "funcionario.cpf: CPF com dígito verificador inválido; funcionario.data_nascimento: data inválida"),
    ('{"funcionario.estado_civil": "enrolado"}', "estado civil não reconhecido"),
    ('{"funcionario.sexo": {"a": 1}}', "formato inesperado"),
])
def test_ler_recusa_dizendo_o_campo(campos, trecho):
    with pytest.raises(informados.CampoInvalido) as erro:
        informados.ler(campos)
    assert trecho in str(erro.value)
    assert "11111111111" not in str(erro.value), "a mensagem nunca repete o valor"


def test_informado_vale_acima_das_leituras_e_tira_os_alertas_dele():
    # O texto diz "casada", mas a certidão de nascimento sem anotação deduz "solteiro": divergente.
    divergente = documentos_completos() + [lido_do_texto(texto(funcionario={"estado_civil": "casada"}))]
    antes = fluxo.concluir(divergente)
    assert any(a["campo"] == "funcionario.estado_civil" and a["tipo"] == "divergente" for a in antes["alertas"])

    r = fluxo.concluir(divergente, informados={"funcionario.estado_civil": "casado",
                                               "funcionario.raca_cor": "branca"})
    assert r["ficha"]["funcionario"]["estado_civil"] == "casado"
    assert r["origens"]["funcionario.estado_civil"] == [INFORMADO]
    assert not any(a["campo"] in ("funcionario.estado_civil", "funcionario.raca_cor") for a in r["alertas"])


def test_informado_preenche_o_que_faltava_e_as_conferencias_valem_para_ele():
    so_rg = [arq("rg.jpg", doc("rg", "Maria Exemplo", cpf=CPF, data_nascimento="05/03/1990"))]
    r = fluxo.concluir(so_rg)
    assert any(a["campo"] == "funcionario.endereco.cep" and a["tipo"] == "ausente" for a in r["alertas"])
    r = fluxo.concluir(so_rg, informados={"funcionario.endereco.cep": "80010-000",
                                          "funcionario.endereco.uf": "SP"})
    assert r["ficha"]["funcionario"]["endereco"]["cep"] == "80010-000"
    tipos = {a["campo"]: a["tipo"] for a in r["alertas"]}
    assert tipos.get("funcionario.endereco.cep") == "invalido", "CEP do Paraná com UF SP continua conferido"


def test_campo_informado_nao_e_relido(monkeypatch):
    monkeypatch.setattr(fluxo, "ler_arquivo", lambda *a: pytest.fail("releu o que a pessoa informou"))
    r = fluxo.concluir([item("rg.jpg", "05/03/1993"), item("cpf.jpg", "05/03/1990")], config=Config(),
                       informados={"funcionario.data_nascimento": "1990-03-05"})
    assert r["ficha"]["funcionario"]["data_nascimento"] == "1990-03-05"
    assert not any(a["campo"] == "funcionario.data_nascimento" for a in r["alertas"])


def test_cpf_informado_no_lugar_do_que_divergia():
    outro = cpf("111444777")
    lidos = [arq("rg.jpg", doc("rg", "Maria Exemplo", cpf=CPF)), arq("cnh.jpg", doc("cnh", "Maria Exemplo", cpf=outro))]
    r = fluxo.concluir(lidos, informados={"funcionario.cpf": CPF})
    assert r["ficha"]["funcionario"]["cpf"] == CPF and r["origens"]["funcionario.cpf"] == [INFORMADO]
