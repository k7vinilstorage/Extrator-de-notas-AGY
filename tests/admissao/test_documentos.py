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
    paginas = [Image.new("RGB", (100, 100), "white") for _ in range(22)]
    paginas[0].save(pdf, save_all=True, append_images=paginas[1:])
    chamadas = agy([rg()])
    r = ler_arquivo(pdf, "docs.pdf", CONFIG)
    assert [len(c["arquivos"]) for c in chamadas] == [4, 4, 4, 4, 4]
    assert r["paginas_lidas"] == list(range(1, 21))
    assert "22 páginas" in r["avisos"][0]["mensagem"]


def test_tipo_indicado_diferente_do_lido(agy, foto):
    chamadas = agy([rg()])
    r = ler_arquivo(foto, "cnh.jpg", CONFIG, dica_tipo="cnh")
    assert "indicado como cnh" in r["avisos"][0]["mensagem"]
    assert "indicou que ele é: cnh" in chamadas[0]["prompt"]


def test_arquivo_sem_documento(agy, foto):
    agy([])
    assert "nenhum documento" in ler_arquivo(foto, "x.jpg", CONFIG)["avisos"][0]["mensagem"]


def test_descricao_do_documento():
    fonte = normalizar_documento({"tipo": "outro", "descricao": " foto 3x4, sem documento ", "nome": None})
    assert (fonte["tipo"], fonte["descricao"]) == ("outro", "foto 3x4, sem documento")


@pytest.mark.parametrize("concluido,situacao,grau", [
    ("sim", "Aprovado", "medio_completo"),
    ("não", "Aprovado", "medio_incompleto"),
    (None, "Aprovado", None),  # "aprovado" num ano não é conclusão do nível
])
def test_escolaridade_pelo_concluido(concluido, situacao, grau):
    fonte = normalizar_documento({"tipo": "comprovante_escolaridade", "nome": "X", "comprovante_escolaridade":
                                  {"nivel": "Ensino Médio", "situacao": situacao, "concluido": concluido}})
    assert fonte["campos"]["grau_instrucao"] == grau


def test_contrato_de_trabalho():
    fonte = normalizar_documento({"tipo": "contrato_trabalho", "nome": "Fulana Teste", "contrato_trabalho": {
        "empregador": "Empresa Exemplo Ltda", "cargo": "Auxiliar Administrativo", "cbo": "4110-05", "salario": "R$ 2.345,67",
        "data_admissao": "07 de Dezembro de 2026", "tipo_contrato": "experiência", "experiencia_dias": "45",
        "prorrogacao_dias": "mais 45 dias", "horario_entrada": "08:00", "horario_saida": "17:00",
        "escala": "ESCALA 6X1", "beneficios": "Auxílio Alimentação; Vale Transporte\nPlano de saúde"}})
    c = fonte["campos"]
    assert (c["cargo"], c["cbo"], c["salario"], c["data_admissao"]) == ("AUXILIAR ADMINISTRATIVO", "411005", 2345.67, "2026-12-07")
    assert (c["tipo_contrato"], c["experiencia_dias"], c["prorrogacao_dias"]) == ("experiencia", 45, 45)
    assert (c["horario_entrada"], c["horario_saida"], c["escala"]) == ("08:00", "17:00", "6x1")
    assert c["beneficios"] == ["AUXÍLIO ALIMENTAÇÃO", "VALE TRANSPORTE", "PLANO DE SAÚDE"]
    assert fonte["problemas"] == []


@pytest.mark.parametrize("opta,esperado", [("sim", True), ("não", False), (None, None)])
def test_declaracao_de_vale_transporte(opta, esperado):
    fonte = normalizar_documento({"tipo": "declaracao_vale_transporte", "nome": "X",
                                  "declaracao_vale_transporte": {"opta": opta}})
    assert fonte["campos"]["opta"] is esperado


def test_pdf_com_texto_vai_junto(agy, tmp_path, monkeypatch):
    pdf = tmp_path / "proposta.pdf"
    Image.new("RGB", (100, 100), "white").save(pdf)
    monkeypatch.setattr(documentos, "texto", lambda caminho, indices: "Cargo: Auxiliar. Remuneração: R$ 2.345,67. " * 3)
    chamadas = agy([])
    ler_arquivo(pdf, "proposta.pdf", CONFIG)
    assert [a.suffix for a in chamadas[0]["arquivos"]] == [".png", ".txt"]
    assert "texto extraído destas páginas" in chamadas[0]["prompt"]


def test_pdf_sem_texto_vai_so_com_imagens(agy, tmp_path):
    pdf = tmp_path / "escaneado.pdf"
    Image.new("RGB", (100, 100), "white").save(pdf)
    chamadas = agy([])
    ler_arquivo(pdf, "escaneado.pdf", CONFIG)
    assert [a.suffix for a in chamadas[0]["arquivos"]] == [".png"]
    assert "texto extraído" not in chamadas[0]["prompt"]


def test_foto_girada_pelo_celular_e_corrigida(tmp_path):
    foto = tmp_path / "rg.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # girar 90° para mostrar
    Image.new("RGB", (40, 20)).save(foto, exif=exif)
    ajustada = documentos.preparar_imagem(foto, tmp_path)
    assert ajustada != foto and Image.open(ajustada).size == (20, 40)


def test_foto_grande_e_reduzida(tmp_path, monkeypatch):
    monkeypatch.setattr(documentos, "MAX_PIXELS_IMAGEM", 1000)
    foto = tmp_path / "grande.png"
    Image.new("RGB", (100, 100)).save(foto)
    ajustada = documentos.preparar_imagem(foto, tmp_path)
    largura, altura = Image.open(ajustada).size
    assert largura * altura <= 1000


def test_foto_normal_segue_como_veio(foto, tmp_path):
    assert documentos.preparar_imagem(foto, tmp_path) == foto


def test_conferir_campos_divergentes(agy, foto):
    chamadas = agy([rg()])
    r = ler_arquivo(foto, "rg.jpg", CONFIG, conferir=["data_nascimento (RG)"])
    assert r["relido"] is True
    assert "divergiram de outro documento da mesma pessoa: data_nascimento (RG)" in chamadas[0]["prompt"]


@pytest.mark.parametrize("nivel,serie,grau", [
    ("ENSINO MÉDIO", "3ª série", "medio_completo"),
    ("Ensino Médio", "3º ANO", "medio_completo"),
    ("ENSINO MÉDIO", "2ª série", None),
    ("Ensino Fundamental", "9º ano", "fundamental_completo"),
    ("Ensino Fundamental", "8ª série", "fundamental_completo"),  # sistema antigo, de 8 séries
    ("Ensino Fundamental", "5º ano", None),
])
def test_grau_pela_serie_final_aprovada(nivel, serie, grau):
    fonte = normalizar_documento({"tipo": "comprovante_escolaridade", "nome": "X", "comprovante_escolaridade":
                                  {"nivel": nivel, "ultima_serie_aprovada": serie}})
    assert fonte["campos"]["grau_instrucao"] == grau
    if grau:
        assert "deduzido do histórico" in fonte["avisos"][0]["mensagem"]


def test_conclusao_declarada_vale_mais_que_a_serie():
    fonte = normalizar_documento({"tipo": "comprovante_escolaridade", "nome": "X", "comprovante_escolaridade":
                                  {"nivel": "Ensino Médio", "ultima_serie_aprovada": "3ª série", "concluido": "não"}})
    assert fonte["campos"]["grau_instrucao"] == "medio_incompleto" and fonte["avisos"] == []


def test_aso():
    fonte = normalizar_documento({"tipo": "aso", "nome": "X", "aso": {"tipo_exame": "Admissional",
                                                                       "data_exame": "28/10/2026", "apto": "sim"}})
    assert (fonte["campos"]["data_exame"], fonte["campos"]["apto"]) == ("2026-10-28", True)
