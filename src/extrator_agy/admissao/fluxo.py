"""Fluxo da admissão: cada arquivo e o texto são uma tarefa; com todas prontas, a ficha.

As tarefas rodam no executor da API, o mesmo de /extrair e /lotes, para que
EXTRATOR_PARALELO limite o total de agy rodando ao mesmo tempo.

Um COMPLEMENTO acrescenta arquivos e texto a uma admissão já lida: só o que é
novo vai ao agy, e a ficha é montada de novo com as leituras de antes e as
novas juntas — quem é quem, divergências e alertas saem da mesma consolidação.
No texto, o que o complemento informa substitui o que o texto de antes dizia
(é como quem confere corrige: "o estado civil é casado").
"""

import copy
from collections.abc import Callable
from functools import partial
from pathlib import Path

from ..agy import DICA_LOGIN, ErroAgy
from ..extracao import Config
from ..pdf import PdfInvalido
from .documentos import ler_arquivo
from .ficha import _nome_contido, montar
from .texto import ler_texto

TEXTO = "texto"


class SemLogin(ErroAgy):
    """O agy está sem login: as outras tarefas falhariam igual, então a admissão para."""


def _erro(nome: str, e: Exception) -> dict:
    if isinstance(e, ErroAgy) and str(e).startswith(DICA_LOGIN):
        raise SemLogin(str(e)) from None
    motivo = f"falha no agy: {e}" if isinstance(e, ErroAgy) else str(e)
    return {"arquivo": nome, "status": "erro", "erro": motivo}


def _ler_arquivo(caminho: Path, nome: str, config: Config, dica_tipo: str | None,
                 conferir: list[str] | None = None) -> dict:
    try:
        resultado = ler_arquivo(caminho, nome, config, dica_tipo, conferir)
    except (ErroAgy, PdfInvalido) as e:
        resultado = _erro(nome, e)
    # Para a releitura; campos com "_" não saem na resposta.
    return resultado | {"_caminho": caminho, "_dica": dica_tipo}


def _ler_texto(texto: str, config: Config, anexos: list[str]) -> dict:
    inclui = {"inclui": anexos} if anexos else {}
    try:
        return {"arquivo": "texto", "status": "ok", "fonte": ler_texto(texto, config)} | inclui
    except ErroAgy as e:
        return _erro("texto", e) | inclui


def juntar_texto(texto: str | None, anexos: list[tuple[str, str]]) -> str | None:
    """O texto digitado seguido do texto de cada anexo (.docx), com o nome do arquivo antes."""
    partes = [texto] if texto else []
    partes += [f"--- conteúdo do arquivo \"{nome}\" ---\n{conteudo}" for nome, conteudo in anexos if conteudo.strip()]
    return "\n\n".join(partes) or None


def tarefas(arquivos: list[tuple[Path, str, str | None]], texto: str | None, config: Config,
            anexos: list[str] | None = None) -> list[Callable[[], dict]]:
    """Uma tarefa por arquivo (caminho, nome original, tipo indicado) e, se houver texto, uma para ele, por último.

    `anexos` são os nomes dos .docx cujo conteúdo já está em `texto`, para a resposta dizer de onde veio.

    Cada tarefa devolve o item do arquivo, com status ok ou erro; só levanta SemLogin.
    """
    lista = [partial(_ler_arquivo, caminho, nome, config, dica) for caminho, nome, dica in arquivos]
    if texto:
        lista.append(partial(_ler_texto, texto, config, anexos or []))
    return lista


def eh_texto(resultado: dict) -> bool:
    """O resultado da tarefa do texto. Arquivo nunca se chama assim: entra só com extensão."""
    return resultado.get("arquivo") == TEXTO


def com_complemento(tarefa: Callable[[], dict], n: int) -> Callable[[], dict]:
    """A tarefa de um complemento: o resultado (e cada fonte dele) sai marcado com o número."""
    def rodar() -> dict:
        resultado = tarefa()
        _marcar(resultado, n)
        return resultado
    return rodar


def _marcar(resultado: dict, n: int | None) -> dict:
    if n:
        resultado["complemento"] = n
        for fonte in resultado.get("fontes") or []:
            fonte["complemento"] = n
        if isinstance(resultado.get("fonte"), dict):
            resultado["fonte"]["complemento"] = n
    return resultado


def mesclar_textos(fontes: list[dict]) -> dict | None:
    """As leituras do texto, da primeira à última, numa fonte só.

    O que um complemento cita (todo campo com trecho, mesmo o que não converteu)
    substitui o que veio antes, com os problemas dele; o resto fica. Dependente
    citado de novo é o mesmo, pelo nome; `outras_informacoes` se somam. Os
    campos vindos de um complemento ficam em `complementos` (campo → número),
    para a origem dizer de qual texto saíram.
    """
    if not fontes:
        return None
    junta = copy.deepcopy(fontes[0])
    junta["complementos"] = {}
    for nova in fontes[1:]:
        n = nova.get("complemento")
        citados = set(nova.get("trechos") or {})
        for campo in citados:
            junta["campos"][campo] = nova["campos"].get(campo)
            junta["trechos"][campo] = nova["trechos"][campo]
            if n:
                junta["complementos"][campo] = n
        junta["problemas"] = [p for p in junta["problemas"] if p["campo"] not in citados] + [
            p | {"campo": f"texto.complemento{n}." + p["campo"][len("texto."):]}
            if p["campo"].startswith("texto.dependentes[") else p
            for p in nova.get("problemas") or []]
        for lido in nova.get("dependentes") or []:
            mesmo = next((d for d in junta["dependentes"] if _nome_contido(lido["nome"], d["nome"])
                          or _nome_contido(d["nome"], lido["nome"])), None)
            novo = {k: v for k, v in lido.items() if v is not None} | ({"complemento": n} if n else {})
            if mesmo is None:
                junta["dependentes"].append(novo)
            else:
                mesmo.update(novo)
        junta["outras_informacoes"] += [i for i in nova.get("outras_informacoes") or []
                                        if i not in junta["outras_informacoes"]]
        junta["avisos"] += nova.get("avisos") or []
    return junta


def _reler(arquivos: list[dict], pedidos: dict[str, list[str]], config: Config) -> list[dict]:
    """Relê, uma vez, os arquivos com campos que divergiram de outro documento.

    Fica a leitura nova só se ela deu certo; com erro, vale a anterior. Arquivo
    de uma rodada anterior (sem `_caminho`: já foi apagado) fica como estava.
    """
    novos = []
    try:
        for item in arquivos:
            conferir = pedidos.get(item["arquivo"])
            if conferir and item["status"] == "ok" and item.get("_caminho"):
                novo = _ler_arquivo(item["_caminho"], item["arquivo"], config, item.get("_dica"), conferir)
                item = _marcar(novo, item.get("complemento")) if novo["status"] == "ok" else item
            novos.append(item)
    except SemLogin:
        return arquivos  # a ficha sai com as leituras que já havia
    return novos


def concluir(resultados: list[dict], config: Config | None = None) -> dict:
    """Monta a ficha a partir dos resultados das tarefas (arquivos e textos, de todas as rodadas).

    Com `config`, os arquivos de campos que divergiram entre documentos são relidos uma vez
    antes da ficha final (pode levar mais uma chamada do agy por arquivo envolvido).

    `documentos` sai na ordem de `resultados`, e `_leituras` traz os resultados que valeram
    (com a releitura): é sobre eles que um complemento monta a ficha de novo.
    """
    arquivos = [r for r in resultados if not eh_texto(r)]
    textos = [r for r in resultados if eh_texto(r)]
    fonte_texto = mesclar_textos([t["fonte"] for t in textos if t["status"] == "ok"])
    r = montar(arquivos, fonte_texto)
    pedidos = r.pop("_reler")
    if pedidos and config is not None:
        arquivos = _reler(arquivos, pedidos, config)
        r = montar(arquivos, fonte_texto)
        r.pop("_reler")
    resumo, lidos = iter(r["documentos"]), iter(arquivos)
    documentos, leituras = [], []
    for resultado in resultados:
        if eh_texto(resultado):
            documentos.append({k: resultado[k] for k in ("arquivo", "status", "erro", "inclui", "complemento")
                               if k in resultado})
            leituras.append(resultado)
        else:
            documentos.append(next(resumo))
            leituras.append(next(lidos))
    r["documentos"] = documentos
    for texto in textos:
        if texto["status"] != "ok":
            de_qual = f"o texto do complemento {texto['complemento']}" if texto.get("complemento") else "o texto"
            r["alertas"].append({"campo": None, "tipo": "aviso", "arquivo": TEXTO,
                                 "mensagem": f"{de_qual} não foi lido; os dados dele estão faltando"})
    r["resultado"] = "alerta" if r["alertas"] else "ok"
    r["_leituras"] = leituras
    return r
