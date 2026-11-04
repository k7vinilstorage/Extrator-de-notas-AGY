import pytest
from PIL import Image

from extrator_agy.admissao import documentos
from extrator_agy.admissao.documentos import ler_arquivo, normalizar_documento
from extrator_agy.agy import DICA_LOGIN, ErroAgy
from extrator_agy.extracao import Config
from numeros import cpf, titulo, trocar_ultimo

CONFIG = Config()


def rg(**campos) -> dict:
    return {"tipo": "rg", "nome": "Maria Exemplo da Silva",
            "rg": {"numero": "12.345.678-9", "cpf": cpf(), "data_nascimento": "05/03/1990", "uf_emissor": "sc"} | campos}


@pytest.fixture
def agy(monkeypatch):
    """Troca o agy por respostas fixas, uma por chamada, e anota cada chamada."""
    chamadas = []

    def configurar(*respostas):
        fila = list(respostas)

        def falso(arquivos, prompt, schema, **kwargs):
            chamadas.append({"arquivos": arquivos, "prompt": prompt, "kwargs": kwargs})
            resposta = fila.pop(0) if len(fila) > 1 else fila[0]
            if isinstance(resposta, Exception):
                raise resposta
            return {"documentos": resposta}

        monkeypatch.setattr(documentos, "transcrever", falso)
        return chamadas
    return configurar


@pytest.fixture
def foto(tmp_path):
    caminho = tmp_path / "foto.jpg"
    Image.new("RGB", (10, 10)).save(caminho)
    return caminho


def test_normaliza_o_documento():
    fonte = normalizar_documento(rg())
    assert fonte["tipo"] == "rg"
    assert fonte["campos"]["nome"] == "MARIA EXEMPLO DA SILVA"
    assert fonte["campos"]["data_nascimento"] == "1990-03-05"
    assert fonte["campos"]["uf_emissor"] == "SC"
    assert fonte["campos"]["cpf"] == cpf()
    assert fonte["campos"]["nome_mae"] is None
    assert fonte["problemas"] == []


def test_valor_invalido_sai_dos_campos_e_vai_para_problemas():
    errado = trocar_ultimo(cpf())
    fonte = normalizar_documento(rg(cpf=errado))
    assert fonte["campos"]["cpf"] is None
    assert fonte["problemas"] == [{"campo": "cpf", "mensagem": "CPF com dígito verificador inválido", "valor": errado}]


def test_uf_do_titulo_confere_com_a_impressa():
    fonte = normalizar_documento({"tipo": "titulo_eleitor", "nome": "X", "titulo_eleitor": {"numero": titulo(uf="09"), "uf": "PR"}})
    assert fonte["campos"]["numero"] is None
    assert "UF do número do título" in fonte["problemas"][0]["mensagem"]


def test_cep_confere_com_a_uf():
    fonte = normalizar_documento({"tipo": "comprovante_residencia", "nome": None,
                                  "comprovante_residencia": {"cep": "01001-000", "uf": "SC"}})
    assert fonte["campos"]["cep"] is None and fonte["problemas"][0]["campo"] == "cep"


def test_matricula_confere_o_livro():
    matricula = "104539" + "01" + "55" + "2010" + "2" + "00012" + "034" + "0001234" + "11"
    fonte = normalizar_documento({"tipo": "certidao_nascimento", "nome": "X", "certidao_nascimento": {"matricula": matricula}})
    assert fonte["campos"]["matricula"] is None and "nascimento" in fonte["problemas"][0]["mensagem"]
    assert normalizar_documento({"tipo": "certidao_casamento", "nome": None,
                                 "certidao_casamento": {"matricula": matricula}})["problemas"] == []


def test_escolaridade_vira_grau_de_instrucao():
    fonte = normalizar_documento({"tipo": "comprovante_escolaridade", "nome": "X", "comprovante_escolaridade":
                                  {"nivel": "Ensino Médio", "situacao": "Concluído"}})
    assert fonte["campos"]["grau_instrucao"] == "medio_completo"
    fonte = normalizar_documento({"tipo": "comprovante_escolaridade", "nome": "X", "comprovante_escolaridade":
                                  {"nivel": "Curso de informática"}})
    assert fonte["campos"]["grau_instrucao"] is None and fonte["avisos"]


def test_tipo_desconhecido_vira_outro():
    assert normalizar_documento({"tipo": "passaporte", "nome": "X"})["tipo"] == "outro"


def test_le_uma_imagem(agy, foto):
    chamadas = agy([rg()])
    r = ler_arquivo(foto, "rg maria.jpg", CONFIG)
    assert r["status"] == "ok" and r["avisos"] == []
    assert [f["tipo"] for f in r["fontes"]] == ["rg"] and r["fontes"][0]["arquivo"] == "rg maria.jpg"
    assert len(chamadas) == 1 and chamadas[0]["kwargs"]["log_temporario"] is True
    assert "certidao_nascimento (certidão de nascimento)" in chamadas[0]["prompt"]


def test_rele_quando_a_validacao_falha_sem_mandar_o_valor(agy, foto):
    errado = trocar_ultimo(cpf())
    chamadas = agy([rg(cpf=errado)], [rg()])
    r = ler_arquivo(foto, "rg.jpg", CONFIG)
    assert r["fontes"][0]["campos"]["cpf"] == cpf() and r["fontes"][0]["revisada"]
    assert len(chamadas) == 2
    assert "campo cpf: CPF com dígito verificador inválido" in chamadas[1]["prompt"]
    assert errado not in chamadas[1]["prompt"] and errado.replace(".", "").replace("-", "") not in chamadas[1]["prompt"]


def test_releitura_pior_e_descartada(agy, foto):
    agy([rg(cpf=trocar_ultimo(cpf()))], [rg(cpf="1", data_nascimento="ontem")])
    fonte = ler_arquivo(foto, "rg.jpg", CONFIG)["fontes"][0]
    assert len(fonte["problemas"]) == 1 and "revisada" not in fonte


def test_sem_revisao(agy, foto):
    chamadas = agy([rg(cpf=trocar_ultimo(cpf()))])
    ler_arquivo(foto, "rg.jpg", Config(revisar=False))
    assert len(chamadas) == 1


def test_falha_do_agy_na_releitura_mantem_a_primeira(agy, foto):
    agy([rg(cpf=trocar_ultimo(cpf()))], ErroAgy("timeout"))
    assert ler_arquivo(foto, "rg.jpg", CONFIG)["fontes"][0]["problemas"]


def test_agy_falha_duas_vezes(agy, foto):
    agy(ErroAgy("timeout"))
    with pytest.raises(ErroAgy):
        ler_arquivo(foto, "rg.jpg", CONFIG)


def test_sem_login_nao_repete(agy, foto):
    chamadas = agy(ErroAgy(DICA_LOGIN))
    with pytest.raises(ErroAgy):
        ler_arquivo(foto, "rg.jpg", CONFIG)
    assert len(chamadas) == 1


def test_pdf_longo_em_grupos_de_paginas(agy, tmp_path):
    pdf = tmp_path / "docs.pdf"
    paginas = [Image.new("RGB", (100, 100), "white") for _ in range(10)]
    paginas[0].save(pdf, save_all=True, append_images=paginas[1:])
    chamadas = agy([rg()])
    r = ler_arquivo(pdf, "docs.pdf", CONFIG)
    assert [len(c["arquivos"]) for c in chamadas] == [4, 4]
    assert r["paginas_lidas"] == list(range(1, 9))
    assert "10 páginas" in r["avisos"][0]["mensagem"]


def test_tipo_indicado_diferente_do_lido(agy, foto):
    chamadas = agy([rg()])
    r = ler_arquivo(foto, "cnh.jpg", CONFIG, dica_tipo="cnh")
    assert "indicado como cnh" in r["avisos"][0]["mensagem"]
    assert "indicou que ele é: cnh" in chamadas[0]["prompt"]


def test_arquivo_sem_documento(agy, foto):
    agy([])
    assert "nenhum documento" in ler_arquivo(foto, "x.jpg", CONFIG)["avisos"][0]["mensagem"]
