"""PDF convertido em imagens antes de ir ao agy.

O agente não lê PDF direto: ele roda pdftotext, python etc., e o agy em modo
não interativo nega comandos e termina sem resposta. Imagem ele abre com
read_file, como as fotos.
"""

from pathlib import Path

import pypdfium2 as pdfium

MAX_PAGINAS = 4
# 150 dpi: os 44 dígitos da chave de um DANFE ficam legíveis e o QR decodifica.
ESCALA = 150 / 72


class PdfInvalido(ValueError):
    pass


def paginas_usadas(total: int) -> list[int]:
    """Índices das páginas lidas: todas, ou as primeiras e as últimas.

    Em cupons longos o emitente fica no começo e o total, a chave e o QR no fim.
    """
    if total <= MAX_PAGINAS:
        return list(range(total))
    metade = MAX_PAGINAS // 2
    return list(range(metade)) + list(range(total - metade, total))


def renderizar(pdf: Path, destino: Path) -> list[Path]:
    """Grava as páginas do PDF como PNG em destino e devolve os caminhos."""
    try:
        documento = pdfium.PdfDocument(pdf)
    except pdfium.PdfiumError as e:
        raise PdfInvalido(f"PDF ilegível ou protegido por senha ({e})") from None
    try:
        paginas = []
        for i in paginas_usadas(len(documento)):
            caminho = destino / f"pagina-{i + 1}.png"
            documento[i].render(scale=ESCALA).to_pil().save(caminho)
            paginas.append(caminho)
    finally:
        documento.close()
    if not paginas:
        raise PdfInvalido("PDF sem páginas")
    return paginas
