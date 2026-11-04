import re
from pathlib import Path

import pytest
from PIL import Image

from extrator_agy.pdf import MAX_PIXELS, PdfInvalido, contar_paginas, paginas_usadas, renderizar, texto


def criar_pdf(caminho, paginas):
    imagens = [Image.new("RGB", (300, 400), "white") for _ in range(paginas)]
    imagens[0].save(caminho, save_all=True, append_images=imagens[1:])
    return caminho


def test_renderiza_cada_pagina_em_png(tmp_path):
    pdf = criar_pdf(tmp_path / "nota.pdf", 2)
    paginas = renderizar(pdf, tmp_path)
    assert [p.name for p in paginas] == ["pagina-1.png", "pagina-2.png"]
    assert Image.open(paginas[0]).format == "PNG"


def test_renderiza_as_paginas_pedidas(tmp_path):
    pdf = criar_pdf(tmp_path / "docs.pdf", 6)
    assert contar_paginas(pdf) == 6
    paginas = renderizar(pdf, tmp_path, indices=[0, 1, 2, 3, 4, 9])
    assert [p.name for p in paginas] == [f"pagina-{i}.png" for i in range(1, 6)]
    assert [p.name for p in renderizar(pdf, tmp_path)] == ["pagina-1.png", "pagina-2.png", "pagina-5.png", "pagina-6.png"]


def test_pdf_longo_usa_o_comeco_e_o_fim():
    assert paginas_usadas(3) == [0, 1, 2]
    assert paginas_usadas(10) == [0, 1, 8, 9]


@pytest.mark.parametrize("conteudo", [b"", b"nao e um pdf"])
def test_pdf_invalido(tmp_path, conteudo):
    pdf = tmp_path / "ruim.pdf"
    pdf.write_bytes(conteudo)
    with pytest.raises(PdfInvalido):
        renderizar(pdf, tmp_path)
    with pytest.raises(PdfInvalido):
        contar_paginas(pdf)


def test_pagina_gigante_respeita_o_teto_de_pixels(tmp_path):
    # 300x400 px a 1 dpi viram uma página de 300x400 polegadas: 45000x60000 px a 150 dpi.
    pdf = tmp_path / "gigante.pdf"
    Image.new("RGB", (300, 400), "white").save(pdf, resolution=1.0)
    imagem = Image.open(renderizar(pdf, tmp_path)[0])
    assert imagem.width * imagem.height <= MAX_PIXELS * 1.01  # o pdfium arredonda os lados para cima


def test_texto_pdf_gerado(tmp_path):
    pdf = criar_pdf(tmp_path / "gerado.pdf", 2)
    assert texto(pdf).strip() == ""  # PDF de imagem, sem camada de texto
    quebrado = tmp_path / "quebrado.pdf"
    quebrado.write_bytes(b"isto nao e um pdf")
    assert texto(quebrado) == ""


# DANFEs reais ficam em notas/, fora do repositório: o teste não cita nenhum pelo nome
# (o nome do arquivo tem a chave de acesso, que permite consultar a nota).
DANFES = sorted(p for p in (Path(__file__).parents[1] / "notas").rglob("*.pdf") if "danfe" in p.name.lower())


@pytest.mark.skipif(not DANFES, reason="nenhum DANFE real em notas/")
def test_texto_de_danfes_reais():
    for n, pdf in enumerate(DANFES, 1):
        conteudo = texto(pdf)
        assert "DANFE" in conteudo.upper(), f"DANFE {n} sem camada de texto"
        assert re.search(r"(?<!\d)\d{8}(?!\d)", conteudo), f"DANFE {n} sem nenhum código de 8 dígitos (NCM)"
