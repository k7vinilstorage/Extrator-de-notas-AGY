import zipfile

import pytest

from extrator_agy.admissao.docx import DocxInvalido, texto_docx

XML = ('<w:document><w:body>'
       '<w:p><w:r><w:t>Banco: Exemplo</w:t></w:r><w:r><w:tab/><w:t xml:space="preserve">Ag: 1234</w:t></w:r></w:p>'
       '<w:p><w:r><w:t>E-mail: fulana@example.com &amp; outro</w:t></w:r></w:p>'
       '<w:p></w:p>'
       '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cargo: SDR</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
       '</w:body></w:document>')


def criar_docx(caminho, xml=XML):
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("word/document.xml", xml)
    return caminho


def test_texto_dos_paragrafos_e_tabelas(tmp_path):
    assert texto_docx(criar_docx(tmp_path / "a.docx")) == \
        "Banco: Exemplo\tAg: 1234\nE-mail: fulana@example.com & outro\nCargo: SDR"


@pytest.mark.parametrize("conteudo", [b"nao e zip", b""])
def test_docx_invalido(tmp_path, conteudo):
    arquivo = tmp_path / "ruim.docx"
    arquivo.write_bytes(conteudo)
    with pytest.raises(DocxInvalido):
        texto_docx(arquivo)


def test_zip_sem_documento(tmp_path):
    with zipfile.ZipFile(tmp_path / "x.docx", "w") as z:
        z.writestr("outra/coisa.xml", "<x/>")
    with pytest.raises(DocxInvalido):
        texto_docx(tmp_path / "x.docx")
