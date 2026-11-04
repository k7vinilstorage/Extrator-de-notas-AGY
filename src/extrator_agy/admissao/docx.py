"""Texto de um .docx (Word), sem dependência: o arquivo é um zip com o XML do documento.

Na admissão chegam .docx com dados bancários, e-mail ou o encaminhamento admissional; o
texto deles vai junto com as informações em texto.
"""

import html
import re
import zipfile
from pathlib import Path

# Um .docx de admissão tem dezenas de KB de XML; isso barra zip bomb.
MAX_XML_BYTES = 5 * 1024 * 1024


class DocxInvalido(ValueError):
    pass


def texto_docx(caminho: Path) -> str:
    """Os parágrafos do documento (e das células de tabela), um por linha."""
    try:
        with zipfile.ZipFile(caminho) as z:
            if z.getinfo("word/document.xml").file_size > MAX_XML_BYTES:
                raise DocxInvalido("documento grande demais")
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        raise DocxInvalido(f".docx ilegível ({type(e).__name__})") from None
    linhas = []
    for paragrafo in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        paragrafo = re.sub(r"<w:tab/>", "\t", paragrafo)
        trechos = re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>|(\t)", paragrafo)
        linha = "".join(t or tab for t, tab in trechos).strip()
        if linha:
            linhas.append(html.unescape(linha))
    return "\n".join(linhas)
