import pytest
from PIL import Image

from extrator_agy.pdf import MAX_PIXELS, PdfInvalido, paginas_usadas, renderizar


def criar_pdf(caminho, paginas):
    imagens = [Image.new("RGB", (300, 400), "white") for _ in range(paginas)]
    imagens[0].save(caminho, save_all=True, append_images=imagens[1:])
    return caminho


def test_renderiza_cada_pagina_em_png(tmp_path):
    pdf = criar_pdf(tmp_path / "nota.pdf", 2)
    paginas = renderizar(pdf, tmp_path)
    assert [p.name for p in paginas] == ["pagina-1.png", "pagina-2.png"]
    assert Image.open(paginas[0]).format == "PNG"


def test_pdf_longo_usa_o_comeco_e_o_fim():
    assert paginas_usadas(3) == [0, 1, 2]
    assert paginas_usadas(10) == [0, 1, 8, 9]


@pytest.mark.parametrize("conteudo", [b"", b"nao e um pdf"])
def test_pdf_invalido(tmp_path, conteudo):
    pdf = tmp_path / "ruim.pdf"
    pdf.write_bytes(conteudo)
    with pytest.raises(PdfInvalido):
        renderizar(pdf, tmp_path)


def test_pagina_gigante_respeita_o_teto_de_pixels(tmp_path):
    # 300x400 px a 1 dpi viram uma página de 300x400 polegadas: 45000x60000 px a 150 dpi.
    pdf = tmp_path / "gigante.pdf"
    Image.new("RGB", (300, 400), "white").save(pdf, resolution=1.0)
    imagem = Image.open(renderizar(pdf, tmp_path)[0])
    assert imagem.width * imagem.height <= MAX_PIXELS * 1.01  # o pdfium arredonda os lados para cima
