"""Leitura de um arquivo de documentos pessoais com o agy e conferência de cada documento lido."""

import re
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from ..agy import DICA_LOGIN, ErroAgy, transcrever
from ..extracao import Config
from ..pdf import contar_paginas, renderizar, texto
from . import regras
from .schema import CAMPOS_DOCUMENTO, DESCRICAO_TIPOS, DOCUMENTOS, TIPOS

# É comum escanear todos os documentos num PDF só, então não dá para ler só o
# começo e o fim como nas notas. Mais páginas que isso numa chamada deixam o agy lento.
MAX_PAGINAS = 20
PAGINAS_POR_CHAMADA = 4
# Foto de celular passa de 8 MP; acima disso o agy fica lento e o texto já sobra.
MAX_PIXELS_IMAGEM = 6_000_000
# Menos que isso na camada de texto de um PDF é só cabeçalho ou lixo de digitalização.
MIN_TEXTO_PDF = 40

PROMPT = """\
Leia {arquivos}: imagens de documentos entregues para a admissão de um funcionário no Brasil.
Uma imagem pode ter mais de um documento (RG e CPF na mesma foto, por exemplo) e um documento pode
estar em mais de uma imagem (frente e verso). Para cada documento encontrado, inclua um item em
"documentos" com:
- tipo: {tipos}.
- descricao: o que é o documento, em poucas palavras e sem nomes nem números (por exemplo
  "carteira de trabalho física, página de identificação" ou "foto 3x4, sem documento").
- nome: o nome da pessoa a quem o documento pertence, como impresso (na certidão de nascimento, o
  registrado; no contrato, o empregado; null na certidão de casamento, que tem os campos dos cônjuges).
- o objeto com o nome do tipo, preenchido; todos os outros objetos null.
Transcreva exatamente como impresso: datas como aparecem, números com a pontuação impressa, nomes
completos. Use null para o que não aparecer ou estiver ilegível. Não invente nem deduza: não preencha
o sexo pelo nome, nem a UF pelo município, por exemplo.
- comprovante_escolaridade: concluido é "sim" se o documento diz que o nível ou curso foi concluído
  (certificado ou diploma de conclusão, histórico que declara a conclusão), "não" se diz que está em
  curso ou incompleto, e null se não diz. "Aprovado" num ano ou série não é conclusão do nível.
  ultima_serie_aprovada: no histórico, a última série ou ano com resultado aprovado, como impresso
  (por exemplo "3ª série").
- contrato_trabalho: tipo_contrato só se o documento disser experiência, prazo determinado ou
  indeterminado ("CLT" sozinho não diz o tipo); horário de entrada e saída como impressos.
- aso: apto é "sim" se o resultado for apto, "não" se inapto.
- declaracao_vale_transporte: opta é "sim" se a opção pelo vale estiver marcada, "não" se estiver
  marcado que não opta, e null se nenhuma estiver marcada.
Só abra os arquivos com read_file; não rode comandos.
"""

DICA_TEXTO_PDF = """\
O arquivo .txt é o texto extraído destas páginas do PDF: use-o para conferir letras e números, mas
ele pode estar incompleto ou fora de ordem.
"""

DICA_TIPO = "Quem enviou o arquivo indicou que ele é: {tipo}. Confira pelo que está impresso.\n"

DICA_REVISAO = """\
Uma leitura anterior destas imagens teve estes problemas: {problemas}.
Releia com atenção, dígito por dígito, os campos envolvidos.
"""

DICA_CONFERIR = """\
Estes campos divergiram de outro documento da mesma pessoa: {campos}.
Releia-os com atenção, dígito por dígito.
"""

# Conferências entre campos do mesmo documento: (tipo, campo que sai, problema, regra).
# A regra recebe os campos e diz se estão coerentes; quando não estão, o campo que sai fica null.
CONFERENCIAS = [
    ("titulo_eleitor", "numero", "UF do número do título difere da UF impressa",
     lambda c: not (c["numero"] and c["uf"]) or regras.uf_do_titulo(c["numero"]) in (c["uf"], "ZZ")),
    ("comprovante_residencia", "cep", "CEP não pertence à UF do endereço",
     lambda c: not (c["cep"] and c["uf"]) or regras.uf_do_cep(c["cep"]) in (None, c["uf"])),
    ("certidao_nascimento", "matricula", "matrícula não é de livro de nascimento",
     lambda c: not c["matricula"] or c["matricula"][14] in regras.LIVRO_MATRICULA["certidao_nascimento"]),
    ("certidao_casamento", "matricula", "matrícula não é de livro de casamento",
     lambda c: not c["matricula"] or c["matricula"][14] in regras.LIVRO_MATRICULA["certidao_casamento"]),
]


def chamar_agy(arquivos: list[Path], prompt: str, schema: dict, config: Config) -> dict:
    """Uma chamada ao agy, repetida uma vez se falhar (menos por falta de login)."""
    kwargs = {"modelo": config.modelo, "timeout_s": config.timeout_s,
              "limpar_historico": config.limpar_historico, "log_temporario": True}
    try:
        return transcrever(arquivos, prompt, schema, **kwargs)
    except ErroAgy as e:
        if str(e).startswith(DICA_LOGIN):
            raise
        return transcrever(arquivos, prompt, schema, **kwargs)


# Última série que conclui o nível: 3ª do médio; 9º ano (ou 8ª série, no sistema antigo) do fundamental.
SERIE_FINAL = [(r"medio|2\W?o? grau|colegial", 3, "medio_completo"),
               (r"fundamental|1\W?o? grau|ginasi", 8, "fundamental_completo")]


def _grau_pela_serie(lidos: dict) -> str | None:
    """Histórico com a série final do nível aprovada: o nível foi concluído."""
    nivel = regras.sem_acento(" ".join(filter(None, (lidos.get("nivel"), lidos.get("curso"))))).lower()
    serie = regras.inteiro(re.sub(r"(?i)\s*(ª|º|°|a\b|o\b)?\s*(serie|série|ano)\b.*", "", lidos.get("ultima_serie_aprovada") or ""))
    for padrao, final, grau in SERIE_FINAL:
        if serie and re.search(padrao, nivel) and serie >= final:
            return grau
    return None


def _grau_instrucao(lidos: dict, concluido: bool | None) -> str | None:
    descricao = " ".join(filter(None, (lidos.get("nivel"), lidos.get("curso"), lidos.get("situacao"))))
    if concluido is not None:
        # O que o agy disse sobre a conclusão vale mais que palavras soltas na situação.
        descricao = " ".join(filter(None, (lidos.get("nivel"), lidos.get("curso"))))
        descricao += " concluído" if concluido else " incompleto"
    return regras.grau_instrucao(descricao)


def normalizar_documento(bruto: dict) -> dict:
    """Converte e confere os campos de um documento lido pelo agy.

    Valor que não passa na conferência sai de `campos` e vai para `problemas`, com o valor
    lido: ele não pode virar dado da ficha, mas quem revisa precisa vê-lo.
    """
    tipo = bruto.get("tipo") if bruto.get("tipo") in TIPOS else "outro"
    lidos = {"nome": bruto.get("nome"), **(bruto.get(tipo) or {})}
    formatos = {"nome": "nome", **CAMPOS_DOCUMENTO.get(tipo, {})}
    campos, problemas, avisos = {}, [], []
    for campo, formato in formatos.items():
        campos[campo], problema = regras.normalizar(formato, lidos.get(campo))
        if problema:
            problemas.append({"campo": campo, "mensagem": problema, "valor": lidos.get(campo)})

    for tipo_conferido, campo, problema, coerente in CONFERENCIAS:
        if tipo == tipo_conferido and not coerente(campos):
            problemas.append({"campo": campo, "mensagem": problema, "valor": lidos.get(campo)})
            campos[campo] = None

    if tipo == "comprovante_escolaridade":
        campos["grau_instrucao"] = _grau_instrucao(lidos, campos.get("concluido"))
        if not campos["grau_instrucao"] and campos.get("concluido") is None and (grau := _grau_pela_serie(lidos)):
            campos["grau_instrucao"] = grau
            avisos.append({"mensagem": "grau de instrução deduzido do histórico (série final do nível aprovada); confirme"})
        if (lidos.get("nivel") or lidos.get("curso")) and not campos["grau_instrucao"]:
            avisos.append({"mensagem": "grau de instrução não definido pelo comprovante de escolaridade"})
    if tipo == "contrato_trabalho" and campos.get("beneficios"):
        # Do valor lido, que ainda tem as quebras de linha da lista.
        itens = re.split(r"[;\n•●○]|,\s(?=[A-ZÀ-Ú])", lidos["beneficios"])
        campos["beneficios"] = [re.sub(r"\s+", " ", b).strip().upper() for b in itens if b.strip()] or None
    descricao = (bruto.get("descricao") or "").strip()
    return {"tipo": tipo, "descricao": descricao or None, "campos": campos, "problemas": problemas, "avisos": avisos}


def _ler_imagens(imagens: list[Path], config: Config, dica_tipo: str | None, extras: str = "") -> list[dict]:
    prompt = PROMPT.replace("{tipos}", "; ".join(f"{t} ({d})" for t, d in DESCRICAO_TIPOS.items()))
    if any(i.suffix == ".txt" for i in imagens):
        prompt += DICA_TEXTO_PDF
    if dica_tipo:
        prompt += DICA_TIPO.format(tipo=dica_tipo)
    prompt += extras

    def ler(problemas: list[str] | None = None) -> list[dict]:
        dica = DICA_REVISAO.format(problemas="; ".join(problemas)) if problemas else ""
        lidos = chamar_agy(imagens, prompt + dica, DOCUMENTOS, config).get("documentos") or []
        return [normalizar_documento(d) for d in lidos if isinstance(d, dict)]

    def contar(fontes: list[dict]) -> int:
        return sum(len(f["problemas"]) for f in fontes)

    fontes = ler()
    if contar(fontes) and config.revisar:
        # Na releitura vai só o problema, nunca o valor lido.
        problemas = [f"{DESCRICAO_TIPOS[f['tipo']]}, campo {p['campo']}: {p['mensagem']}"
                     for f in fontes for p in f["problemas"]]
        try:
            novas = ler(problemas)
        except ErroAgy as e:
            if str(e).startswith(DICA_LOGIN):
                raise
        else:
            if contar(novas) < contar(fontes):
                fontes = novas
                for f in fontes:
                    f["revisada"] = True
    return fontes


def preparar_imagem(caminho: Path, destino: Path) -> Path:
    """Aplica a rotação gravada pelo celular (EXIF) e reduz fotos grandes demais.

    O agy recebe o arquivo como está: sem isso, uma foto "em pé" pode chegar deitada.
    Imagem que não precisa de ajuste (ou que não abre) segue como veio.
    """
    try:
        with Image.open(caminho) as original:
            girada = original.getexif().get(0x0112, 1) != 1  # tag Orientation
            imagem = ImageOps.exif_transpose(original) if girada else original
            pixels = imagem.width * imagem.height
            if not girada and pixels <= MAX_PIXELS_IMAGEM:
                return caminho
            if pixels > MAX_PIXELS_IMAGEM:
                escala = (MAX_PIXELS_IMAGEM / pixels) ** 0.5
                imagem = imagem.resize((int(imagem.width * escala), int(imagem.height * escala)), Image.LANCZOS)
            saida = destino / f"{caminho.stem}-ajustada.jpg"
            imagem.convert("RGB").save(saida, quality=90)
            return saida
    except (OSError, Image.DecompressionBombError):
        return caminho


def ler_arquivo(caminho: Path, nome: str, config: Config, dica_tipo: str | None = None,
                conferir: list[str] | None = None) -> dict:
    """Lê os documentos de um arquivo (imagem ou PDF).

    `conferir` são campos que divergiram de outro documento: o agy é avisado para relê-los
    com atenção (sem saber o valor de nenhum dos lados).
    Levanta ErroAgy se o agy falhar duas vezes seguidas e PdfInvalido se o PDF não abrir.
    """
    resultado = {"arquivo": nome, "status": "ok", "avisos": []}
    extras = DICA_CONFERIR.format(campos="; ".join(conferir)) if conferir else ""
    with tempfile.TemporaryDirectory(prefix="extrator-paginas-") as tmp:
        grupos = []
        if caminho.suffix.lower() == ".pdf":
            total = contar_paginas(caminho)
            indices = list(range(min(total, MAX_PAGINAS)))
            imagens = renderizar(caminho, Path(tmp), indices)
            resultado["paginas_lidas"] = list(range(1, len(imagens) + 1))
            if total > MAX_PAGINAS:
                resultado["avisos"].append({"mensagem": f"PDF com {total} páginas: só as {MAX_PAGINAS} primeiras foram lidas"})
            for i in range(0, len(imagens), PAGINAS_POR_CHAMADA):
                grupo = imagens[i:i + PAGINAS_POR_CHAMADA]
                camada = texto(caminho, indices[i:i + PAGINAS_POR_CHAMADA])
                if len(camada.strip()) >= MIN_TEXTO_PDF:
                    arquivo_texto = Path(tmp) / f"texto-{i}.txt"
                    arquivo_texto.write_text(camada, encoding="utf-8")
                    grupo = [*grupo, arquivo_texto]
                grupos.append(grupo)
        else:
            grupos.append([preparar_imagem(caminho, Path(tmp))])
        fontes = []
        for grupo in grupos:
            fontes += _ler_imagens(grupo, config, dica_tipo, extras)

    for fonte in fontes:
        fonte["arquivo"] = nome
    if not fontes:
        resultado["avisos"].append({"mensagem": "nenhum documento encontrado no arquivo"})
    elif dica_tipo and dica_tipo not in {f["tipo"] for f in fontes}:
        resultado["avisos"].append({"mensagem": f"o arquivo foi indicado como {dica_tipo}, mas o agy leu outro tipo"})
    if conferir:
        resultado["relido"] = True
    resultado["fontes"] = fontes
    return resultado
