"""Leitura de verdade, com o agy, dos documentos sintéticos de tests/admissao/sinteticos.

Gasta cota e leva cerca de 1 min, então só roda com EXTRATOR_TESTE_AGY=1. Confere os
campos que importam, e não o JSON inteiro: o modelo varia em detalhes como o órgão emissor.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from extrator_agy.admissao import fluxo
from extrator_agy.extracao import Config

PASTA = Path(__file__).parent / "sinteticos"

pytestmark = pytest.mark.skipif(
    os.environ.get("EXTRATOR_TESTE_AGY") != "1" or not PASTA.exists(),
    reason="leitura real com o agy: rode com EXTRATOR_TESTE_AGY=1",
)


@pytest.fixture(scope="module")
def admissao():
    arquivos = [(PASTA / "cin-fulana.png", "cin.png", None), (PASTA / "certidoes.pdf", "certidoes.pdf", None)]
    texto = (PASTA / "texto.txt").read_text(encoding="utf-8")
    config = Config(limpar_historico=True, timeout_s=180)
    with ThreadPoolExecutor(4) as executor:
        resultados = list(executor.map(lambda tarefa: tarefa(), fluxo.tarefas(arquivos, texto, config)))
    return fluxo.concluir(resultados)


def test_titular(admissao):
    f = admissao["ficha"]["funcionario"]
    assert (f["nome"], f["cpf"], f["data_nascimento"]) == ("FULANA TESTE DE SOUZA", "123.456.789-09", "1990-03-05")
    assert (f["sexo"], f["estado_civil"], f["raca_cor"], f["grau_instrucao"]) == ("F", "casado", "branca", "medio_completo")
    assert (f["nome_mae"], f["uf_nascimento"]) == ("CICLANA TESTE DE SOUZA", "SC")


def test_dependentes(admissao):
    dependentes = {d["nome"]: d for d in admissao["ficha"]["dependentes"]}
    filho = dependentes["CICLANO TESTE DE SOUZA"]
    assert (filho["cpf"], filho["data_nascimento"], filho["parentesco"], filho["irrf"]) == \
        ("987.654.321-00", "2015-02-01", "filho", True)
    assert dependentes["FULANO DE TAL SOUZA"]["parentesco"] == "conjuge"


def test_contrato(admissao):
    c = admissao["ficha"]["contrato"]
    assert (c["data_admissao"], c["cargo"], c["salario"]) == ("2026-12-01", "AUXILIAR ADMINISTRATIVO", 2100.0)
    assert (c["tipo_contrato"], c["experiencia"]) == ("experiencia", {"dias": 30, "prorrogacao_dias": 60})
    assert (c["horario"]["entrada"], c["horario"]["saida"], c["horario"]["intervalo_minutos"]) == ("08:00", "17:00", 60)
    assert c["vale_transporte"] is True


def test_sem_divergencia_nem_valor_invalido(admissao):
    # Faltam só o endereço (não há comprovante) e avisos, como o do cônjuge.
    assert [a for a in admissao["alertas"] if a["tipo"] in ("invalido", "divergente")] == []
    assert {a["campo"] for a in admissao["alertas"] if a["tipo"] == "ausente"} <= {
        "funcionario.endereco.cep", "funcionario.endereco.logradouro", "funcionario.endereco.municipio",
        "funcionario.endereco.uf"}
