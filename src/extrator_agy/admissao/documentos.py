"""Leitura de um arquivo de documentos pessoais com o agy e conferência de cada documento lido."""

import tempfile
from pathlib import Path

from ..agy import DICA_LOGIN, ErroAgy, transcrever
from ..extracao import Config
from ..pdf import contar_paginas, renderizar
from . import regras
from .schema import CAMPOS_DOCUMENTO, DESCRICAO_TIPOS, DOCUMENTOS, TIPOS

# É comum escanear vários documentos num PDF só, então não dá para ler só o
# começo e o fim como nas notas. Mais páginas que isso numa chamada deixam o agy lento.
MAX_PAGINAS = 8
PAGINAS_POR_CHAMADA = 4

PROMPT = """\
Leia {arquivos}: imagens de documentos pessoais brasileiros entregues para a admissão de um funcionário.
Uma imagem pode ter mais de um documento (RG e CPF na mesma foto, por exemplo) e um documento pode
estar em mais de uma imagem (frente e verso). Para cada documento encontrado, inclua um item em
"documentos" com:
- tipo: {tipos}.
- nome: o nome da pessoa a quem o documento pertence, como impresso (na certidão de nascimento, o
  registrado; null na certidão de casamento, que tem os campos dos cônjuges).
- o objeto com o nome do tipo, preenchido; todos os outros objetos null.
Transcreva exatamente como impresso: datas como aparecem, números com a pontuação impressa, nomes
completos. Use null para o que não aparecer ou estiver ilegível. Não invente nem deduza: não preencha
o sexo pelo nome, nem a UF pelo município, por exemplo.
Só abra as imagens com read_file; não rode comandos.
"""

DICA_TIPO = "Quem enviou o arquivo indicou que ele é: {tipo}. Confira pelo que está impresso.\n"

DICA_REVISAO = """\
Uma leitura anterior destas imagens teve estes problemas: {problemas}.
Releia com atenção, dígito por dígito, os campos envolvidos.
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
        descricao = " ".join(filter(None, (lidos.get("nivel"), lidos.get("curso"), lidos.get("situacao"))))
        campos["grau_instrucao"] = regras.grau_instrucao(descricao)
        if descricao and not campos["grau_instrucao"]:
            avisos.append({"mensagem": "grau de instrução não definido pelo comprovante de escolaridade"})
    return {"tipo": tipo, "campos": campos, "problemas": problemas, "avisos": avisos}


def _ler_imagens(imagens: list[Path], config: Config, dica_tipo: str | None) -> list[dict]:
    prompt = PROMPT.replace("{tipos}", "; ".join(f"{t} ({d})" for t, d in DESCRICAO_TIPOS.items()))
    if dica_tipo:
        prompt += DICA_TIPO.format(tipo=dica_tipo)

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


def ler_arquivo(caminho: Path, nome: str, config: Config, dica_tipo: str | None = None) -> dict:
    """Lê os documentos de um arquivo (imagem ou PDF).

    Levanta ErroAgy se o agy falhar duas vezes seguidas e PdfInvalido se o PDF não abrir.
    """
    resultado = {"arquivo": nome, "status": "ok", "avisos": []}
    with tempfile.TemporaryDirectory(prefix="extrator-paginas-") as tmp:
        if caminho.suffix.lower() == ".pdf":
            total = contar_paginas(caminho)
            imagens = renderizar(caminho, Path(tmp), list(range(min(total, MAX_PAGINAS))))
            resultado["paginas_lidas"] = list(range(1, len(imagens) + 1))
            if total > MAX_PAGINAS:
                resultado["avisos"].append({"mensagem": f"PDF com {total} páginas: só as {MAX_PAGINAS} primeiras foram lidas"})
        else:
            imagens = [caminho]
        fontes = []
        for i in range(0, len(imagens), PAGINAS_POR_CHAMADA):
            fontes += _ler_imagens(imagens[i:i + PAGINAS_POR_CHAMADA], config, dica_tipo)

    for fonte in fontes:
        fonte["arquivo"] = nome
    if not fontes:
        resultado["avisos"].append({"mensagem": "nenhum documento encontrado no arquivo"})
    elif dica_tipo and dica_tipo not in {f["tipo"] for f in fontes}:
        resultado["avisos"].append({"mensagem": f"o arquivo foi indicado como {dica_tipo}, mas o agy leu outro tipo"})
    resultado["fontes"] = fontes
    return resultado
