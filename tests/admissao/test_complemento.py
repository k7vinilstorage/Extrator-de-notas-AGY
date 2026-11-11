"""Complemento: arquivos e texto acrescentados a uma admissão já lida (a consolidação)."""

import pytest
from test_ficha import CPF, arq, doc, documentos_completos, texto
from test_fluxo import item

from extrator_agy.admissao import fluxo
from extrator_agy.admissao.texto import normalizar_texto
from extrator_agy.extracao import Config


def lido_do_texto(fonte: dict) -> dict:
    return {"arquivo": "texto", "status": "ok", "fonte": fonte}


def do_complemento(n: int, resultado: dict) -> dict:
    return fluxo.com_complemento(lambda: resultado, n)()


def test_texto_do_complemento_substitui_so_o_que_ele_cita():
    primeiro = texto(contrato={"salario": "dois mil e pouco"}, dependentes=[
        {"nome": "João", "parentesco": "filho", "irrf": "não", "salario_familia": None, "trecho": "João não"}])
    primeiro["outras_informacoes"] = ["começa na filial do centro"]
    complemento = normalizar_texto({
        "funcionario": {"raca_cor": {"valor": "branca", "trecho": "é branca"}},
        "contrato": {"salario": {"valor": "R$ 2.800,00", "trecho": "salário de 2.800"}},
        "dependentes": [{"nome": "João Exemplo", "irrf": "sim", "trecho": "o João entra no IR"}],
        "outras_informacoes": ["começa na filial do centro", "usa uniforme G"],
    })
    r = fluxo.concluir(documentos_completos() + [lido_do_texto(primeiro),
                                                 do_complemento(1, lido_do_texto(complemento))])
    f, c = r["ficha"]["funcionario"], r["ficha"]["contrato"]
    assert (f["raca_cor"], c["salario"]) == ("branca", 2800.0), "o complemento corrige"
    assert (f["estado_civil"], c["cargo"]) == ("solteiro", "AUXILIAR ADMINISTRATIVO"), "o que ele não cita fica"
    assert not any(a["campo"] == "contrato.salario" for a in r["alertas"]), "o problema do salário antigo sai"
    assert r["origens"]["contrato.salario"] == [{"arquivo": "texto", "tipo": "texto", "trecho": "salário de 2.800",
                                                 "complemento": 1}]
    assert "complemento" not in r["origens"]["contrato.cargo"][0]
    [joao] = r["ficha"]["dependentes"]
    assert joao["irrf"] is True, "o mesmo dependente, pelo nome"
    assert any(o.get("complemento") == 1 for o in r["origens"]["dependentes[0].irrf"])
    assert r["ficha"]["outras_informacoes"] == ["começa na filial do centro", "usa uniforme G"]
    assert [(d["arquivo"], d.get("complemento")) for d in r["documentos"][-2:]] == [("texto", None), ("texto", 1)]


def test_documento_do_complemento_e_consolidado_com_os_de_antes():
    antes = [a for a in documentos_completos() if a["arquivo"] not in ("filho.jpg", "cpf-filho.jpg")]
    certidao = arq("pedro.jpg (complemento 1)", doc("certidao_nascimento", "Pedro Exemplo da Silva",
                                                    data_nascimento="01/02/2016", sexo="M",
                                                    nome_mae="Maria Exemplo da Silva"))
    r = fluxo.concluir(antes + [lido_do_texto(texto()), do_complemento(1, certidao)])
    assert r["ficha"]["funcionario"]["nome"] == "MARIA EXEMPLO DA SILVA" and r["ficha"]["funcionario"]["cpf"] == CPF
    [pedro] = r["ficha"]["dependentes"]
    assert (pedro["nome"], pedro["parentesco"]) == ("PEDRO EXEMPLO DA SILVA", "filho"), \
        "a certidão nova é ligada à mãe que veio nos documentos de antes"
    novo = r["documentos"][-1]
    assert (novo["arquivo"], novo["complemento"], novo["pessoas"]) == ("pedro.jpg (complemento 1)", 1, ["dependente:1"])
    assert r["origens"]["dependentes[0].nome"][0]["complemento"] == 1


def test_concluir_devolve_as_leituras_que_valeram(monkeypatch):
    monkeypatch.setattr(fluxo, "ler_arquivo", lambda caminho, nome, config, dica, conferir: item(nome, "05/03/1990"))
    r = fluxo.concluir([item("rg.jpg", "05/03/1993"), item("cpf.jpg", "05/03/1990")], config=Config())
    assert [l["fontes"][0]["campos"]["data_nascimento"] for l in r["_leituras"]] == ["1990-03-05"] * 2, \
        "a releitura é o que fica para o próximo complemento"


def test_arquivo_de_rodada_anterior_nao_e_relido(monkeypatch):
    monkeypatch.setattr(fluxo, "ler_arquivo", lambda *a: pytest.fail("releu um arquivo que já foi apagado"))
    antigos = [item("rg.jpg", "05/03/1993") | {"_caminho": None}, item("cpf.jpg", "05/03/1990") | {"_caminho": None}]
    r = fluxo.concluir(antigos, config=Config())
    assert any(a["campo"] == "funcionario.data_nascimento" and a["tipo"] == "divergente" for a in r["alertas"])


def test_texto_que_nao_foi_lido_diz_de_qual_rodada():
    r = fluxo.concluir(documentos_completos() + [lido_do_texto(texto()),
                                                 do_complemento(2, {"arquivo": "texto", "status": "erro", "erro": "x"})])
    assert any(a["mensagem"].startswith("o texto do complemento 2 não foi lido") for a in r["alertas"])
    assert r["ficha"]["contrato"]["cargo"] == "AUXILIAR ADMINISTRATIVO", "o texto de antes continua valendo"
