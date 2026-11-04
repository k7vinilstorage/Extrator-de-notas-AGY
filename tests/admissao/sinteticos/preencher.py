"""Preenche os espécimes oficiais (CIN do Serpro, certidões do Provimento CNJ 182) com dados sintéticos."""
import statistics
import sys
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont

BAIXADOS, SAIDA = Path(sys.argv[1]), Path(sys.argv[2])
FONTE = "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf"
FONTE_FINA = "/usr/share/fonts/liberation-narrow/LiberationSansNarrow-Regular.ttf"


def fundo(img, caixa):
    x0, y0, x1, y1 = caixa
    px = img.load()
    claros = [px[x, y] for x in range(x0, x1, 2) for y in range(y0, y1, 2) if sum(px[x, y]) > 600]
    if not claros:
        return (240, 245, 235)
    return tuple(int(statistics.median(c[i] for c in claros)) for i in range(3))


def escrever(img, escala, campos, fonte=FONTE, centro=False):
    d = ImageDraw.Draw(img)
    for x0, y0, x1, y1, texto in campos:
        caixa = tuple(round(v * escala) for v in (x0, y0, x1, y1))
        d.rectangle(caixa, fill=fundo(img, caixa))
        if not texto:
            continue
        altura = caixa[3] - caixa[1]
        tamanho = int(altura * 0.85)
        while True:
            f = ImageFont.truetype(fonte, tamanho)
            largura = d.textlength(texto, font=f)
            if largura <= caixa[2] - caixa[0] or tamanho <= 6:
                break
            tamanho -= 1
        x = caixa[0] + ((caixa[2] - caixa[0] - largura) / 2 if centro else 2)
        d.text((x, caixa[1] + altura / 2), texto, fill=(20, 20, 20), font=f, anchor="lm")


# --- CIN em papel (frente e verso), 768x267 ampliada 2x ---
cin = Image.open(BAIXADOS / "cin-papel.jpg").convert("RGB")
cin = cin.resize((cin.width * 2, cin.height * 2), Image.LANCZOS)
escrever(cin, 2, [
    (147, 88, 374, 97, "FULANA TESTE DE SOUZA"), (147, 98, 374, 107, ""),
    (147, 116, 374, 125, ""), (147, 126, 374, 134, ""),
    (147, 145, 230, 154, "123.456.789-09"), (273, 145, 312, 154, "FEMININO"),
    (147, 166, 215, 178, "05 / 03 / 1990"), (273, 166, 375, 178, "BRASILEIRA"),
    (147, 187, 265, 201, "JOINVILLE/SC"), (273, 187, 340, 201, "10 / 08 / 2034"),
    (499, 48, 726, 59, "CICLANA TESTE DE SOUZA"), (499, 59, 726, 70, "BELTRANO DE SOUZA"),
    (499, 70, 726, 81, ""), (499, 81, 726, 92, ""),
    (499, 93, 726, 104, "SECRETARIA DE SEGURANCA PUBLICA"), (499, 104, 726, 115, "SSP/SC"), (499, 115, 726, 122, ""),
    (499, 138, 600, 149, "JOINVILLE / SC"), (627, 138, 695, 149, "10 / 08 / 2024"),
])
cin.save(SAIDA / "cin-fulana.png")

# --- Certidões: páginas 6 e 7 do Provimento 182 a 150 dpi; coordenadas medidas na prévia a 0.8 ---
pdf = pdfium.PdfDocument(BAIXADOS / "cnj-prov-182.pdf")
escala = 1  # coordenadas medidas na página renderizada a 150 dpi


def pagina(i):
    return pdf[i].render(scale=150 / 72).to_pil().convert("RGB")


nasc = pagina(5)
escrever(nasc, escala, [
    (245, 383, 990, 410, "CICLANO TESTE DE SOUZA"),
    (108, 437, 1119, 461, "987.654.321-00"),
    (365, 488, 885, 515, "104539 01 55 2015 1 00012 034 0001234 11"),
    (106, 544, 865, 567, "PRIMEIRO DE FEVEREIRO DE DOIS MIL E QUINZE"),
    (865, 544, 945, 567, "01"), (945, 544, 1035, 567, "02"), (1035, 544, 1121, 567, "2015"),
    (106, 592, 420, 614, "08:15 HORAS"), (420, 592, 1033, 614, "JOINVILLE"), (1033, 592, 1121, 614, "SC"),
    (106, 638, 490, 661, "HOSPITAL MUNICIPAL"), (490, 638, 893, 661, "JOINVILLE"),
    (893, 638, 965, 661, "SC"), (965, 638, 1121, 661, "MASCULINO"),
    (106, 695, 580, 720, "FULANA TESTE DE SOUZA"), (580, 695, 985, 720, "JOINVILLE"), (985, 695, 1121, 720, "SC"),
    (106, 744, 1121, 767, "CICLANA TESTE DE SOUZA; BELTRANO DE SOUZA"),
    (106, 801, 580, 825, "FULANO DE TAL SOUZA"), (580, 801, 985, 825, "BLUMENAU"), (985, 801, 1121, 825, "SC"),
    (106, 846, 1121, 882, "MARIA DE TAL; JOSE DE TAL"),
    (106, 921, 1121, 968, ""),
    (106, 992, 665, 1017, "DEZ DE FEVEREIRO DE DOIS MIL E QUINZE"), (665, 992, 1121, 1017, "31-12345678-9"),
    (106, 1036, 1121, 1061, ""), (106, 1081, 1121, 1106, ""),
], fonte=FONTE_FINA, centro=True)
nasc.save(SAIDA / "certidao-nascimento-ciclano.png")

cas = pagina(6)
escrever(cas, escala, [
    (106, 383, 752, 408, "FULANA TESTE DE SOUZA"), (786, 383, 1121, 408, "123.456.789-09"),
    (106, 430, 752, 456, "FULANO DE TAL SOUZA"), (786, 430, 1121, 456, "111.444.777-35"),
    (365, 503, 885, 530, "104539 01 55 2013 2 00004 112 0000456 22"),
    (106, 552, 775, 578, "FULANA TESTE"), (775, 552, 910, 578, "05"), (910, 552, 1035, 578, "03"), (1035, 552, 1121, 578, "1990"),
    (106, 598, 340, 625, "BRASILEIRA"), (340, 598, 580, 625, "SOLTEIRA"), (580, 598, 1035, 625, "JOINVILLE"), (1035, 598, 1121, 625, "SC"),
    (106, 646, 1121, 671, "CICLANA TESTE DE SOUZA; BELTRANO DE SOUZA"),
    (106, 686, 1121, 714, "FULANA TESTE DE SOUZA"),
    (106, 754, 775, 790, "FULANO DE TAL SOUZA"), (775, 754, 910, 790, "20"), (910, 754, 1035, 790, "07"), (1035, 754, 1121, 790, "1988"),
    (106, 797, 340, 826, "BRASILEIRO"), (340, 797, 580, 826, "SOLTEIRO"), (580, 797, 1035, 826, "BLUMENAU"), (1035, 797, 1121, 826, "SC"),
    (106, 845, 1121, 870, "MARIA DE TAL; JOSE DE TAL"),
    (106, 888, 1121, 917, "FULANO DE TAL SOUZA"),
    (106, 951, 810, 978, "QUINZE DE JUNHO DE DOIS MIL E TREZE"), (810, 951, 910, 978, "15"), (910, 951, 1035, 978, "06"), (1035, 951, 1121, 978, "2013"),
    (106, 1013, 1121, 1039, "COMUNHAO PARCIAL DE BENS"),
    (106, 1078, 810, 1105, "QUINZE DE JUNHO DE DOIS MIL E TREZE"), (810, 1078, 910, 1105, "15"), (910, 1078, 1035, 1105, "06"), (1035, 1078, 1121, 1105, "2013"),
    (106, 1123, 1121, 1148, ""), (106, 1168, 1121, 1193, ""),
], fonte=FONTE_FINA, centro=True)
cas.save(SAIDA / "certidao-casamento-fulana.png")
print("ok")
