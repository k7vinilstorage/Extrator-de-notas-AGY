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


def texto(pdf: Path) -> str:
    """Texto das páginas lidas, para conferir o NCM; vazio em PDF escaneado ou ilegível."""
    with _PDFIUM:
        try:
            documento = pdfium.PdfDocument(pdf)
        except pdfium.PdfiumError:
            return ""
        try:
            return "\n".join(documento[i].get_textpage().get_text_range() for i in paginas_usadas(len(documento)))
        finally:
            documento.close()


def renderizar(pdf: Path, destino: Path) -> list[Path]:
    """Grava as páginas do PDF como PNG em destino e devolve os caminhos."""
    with _PDFIUM:
        try:
            documento = pdfium.PdfDocument(pdf)
        except pdfium.PdfiumError as e:
            raise PdfInvalido(f"PDF ilegível ou protegido por senha ({e})") from None
        try:
            paginas = []
            for i in paginas_usadas(len(documento)):
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
