"""PDF convertido em imagens antes de ir ao agy.

O agente não lê PDF direto: ele roda pdftotext, python etc., e o agy em modo
não interativo nega comandos e termina sem resposta. Imagem ele abre com
read_file, como as fotos.
"""

import threading
from pathlib import Path

import pypdfium2 as pdfium

MAX_PAGINAS = 4
# 150 dpi: os 44 dígitos da chave de um DANFE ficam legíveis e o QR decodifica.
ESCALA = 150 / 72
# Teto por página (A4 a 150 dpi tem 2,2 milhões): PDF pode ter página de metros de
# lado, que a 150 dpi passaria de 1 GB de memória.
MAX_PIXELS = 16_000_000
# O pdfium não é thread-safe: dois PDFs abertos ao mesmo tempo (a API e a CLI processam
# em paralelo) corrompem a memória e derrubam o processo. Cada PDF leva décimos de segundo.
_PDFIUM = threading.Lock()


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


def texto(pdf: Path, indices: list[int] | None = None) -> str:
    """Texto das páginas lidas (ou das de `indices`); vazio em PDF escaneado ou ilegível."""
    with _PDFIUM:
        try:
            documento = pdfium.PdfDocument(pdf)
        except pdfium.PdfiumError:
            return ""
        try:
            total = len(documento)
            escolhidas = paginas_usadas(total) if indices is None else [i for i in indices if 0 <= i < total]
            return "\n".join(documento[i].get_textpage().get_text_range() for i in escolhidas)
        finally:
            documento.close()


def _abrir(pdf: Path) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(pdf)
    except pdfium.PdfiumError as e:
        raise PdfInvalido(f"PDF ilegível ou protegido por senha ({e})") from None


def contar_paginas(pdf: Path) -> int:
    with _PDFIUM:
        documento = _abrir(pdf)
        try:
            return len(documento)
        finally:
            documento.close()


def renderizar(pdf: Path, destino: Path, indices: list[int] | None = None) -> list[Path]:
    """Grava as páginas do PDF como PNG em destino e devolve os caminhos.

    `indices` escolhe as páginas (a partir de 0); sem ele, as de `paginas_usadas`.
    """
    with _PDFIUM:
        documento = _abrir(pdf)
        try:
            paginas = []
            total = len(documento)
            for i in paginas_usadas(total) if indices is None else [i for i in indices if 0 <= i < total]:
                pagina = documento[i]
                largura, altura = pagina.get_size()
                escala = min(ESCALA, (MAX_PIXELS / max(largura * altura, 1)) ** 0.5)
                caminho = destino / f"pagina-{i + 1}.png"
                pagina.render(scale=escala).to_pil().save(caminho)
                paginas.append(caminho)
        finally:
            documento.close()
    if not paginas:
        raise PdfInvalido("PDF sem páginas")
    return paginas
