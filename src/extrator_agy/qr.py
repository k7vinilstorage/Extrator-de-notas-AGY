"""Leitura local do QR code do cupom, que traz a chave de acesso exata."""

import re
from pathlib import Path

import zxingcpp
from PIL import Image, ImageOps

from .validacao import chave_valida

# Acima disso a foto não é ampliada: 2x numa foto de 50 MP passaria de 500 MB, e
# nela o QR já tem pixels de sobra.
MAX_PIXELS_AMPLIAR = 12_000_000


def _decodificar(imagem: Image.Image) -> list[str]:
    return [
        r.text
        for r in zxingcpp.read_barcodes(imagem)
        if r.format == zxingcpp.BarcodeFormat.QRCode
    ]


def ler_chave_qr(arquivo: Path) -> str | None:
    """Retorna a chave de acesso do QR code da imagem, ou None se não conseguir ler."""
    try:
        imagem = ImageOps.exif_transpose(Image.open(arquivo))
    except (OSError, Image.DecompressionBombError):
        return None

    textos = _decodificar(imagem)
    if not textos and imagem.width * imagem.height <= MAX_PIXELS_AMPLIAR:
        # QR pequeno na foto: ampliar em tons de cinza costuma resolver.
        cinza = ImageOps.grayscale(imagem)
        textos = _decodificar(cinza.resize((cinza.width * 2, cinza.height * 2)))

    # Só sequências de exatamente 44 dígitos (NFC-e, CF-e SAT) ou 50 (NFS-e, cujo QR é uma URL
    # com a chave): os primeiros 44 dígitos de uma chave de NFS-e às vezes passam no DV.
    for texto in textos:
        for chave in re.findall(r"(?<!\d)(?:\d{50}|\d{44})(?!\d)", texto):
            if chave_valida(chave):
                return chave
    return None
