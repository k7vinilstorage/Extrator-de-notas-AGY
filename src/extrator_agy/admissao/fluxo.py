"""Fluxo da admissão: cada arquivo e o texto são uma tarefa; com todas prontas, a ficha.

As tarefas rodam no executor da API, o mesmo de /extrair e /lotes, para que
EXTRATOR_PARALELO limite o total de agy rodando ao mesmo tempo.
"""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from ..agy import DICA_LOGIN, ErroAgy
from ..extracao import Config
from ..pdf import PdfInvalido
from .documentos import ler_arquivo
from .ficha import montar
from .texto import ler_texto


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


def _reler(arquivos: list[dict], pedidos: dict[str, list[str]], config: Config) -> list[dict]:
    """Relê, uma vez, os arquivos com campos que divergiram de outro documento.

    Fica a leitura nova só se ela deu certo; com erro, vale a anterior.
    """
    novos = []
    try:
        for item in arquivos:
            conferir = pedidos.get(item["arquivo"])
            if conferir and item["status"] == "ok" and item.get("_caminho"):
                novo = _ler_arquivo(item["_caminho"], item["arquivo"], config, item.get("_dica"), conferir)
                item = novo if novo["status"] == "ok" else item
            novos.append(item)
    except SemLogin:
        return arquivos  # a ficha sai com as leituras que já havia
    return novos


def concluir(resultados: list[dict], com_texto: bool, config: Config | None = None) -> dict:
    """Monta a ficha a partir dos resultados das tarefas, na ordem de `tarefas`.

    Com `config`, os arquivos de campos que divergiram entre documentos são relidos uma vez
    antes da ficha final (pode levar mais uma chamada do agy por arquivo envolvido).
    """
    arquivos, texto = (resultados[:-1], resultados[-1]) if com_texto else (resultados, None)
    fonte_texto = texto["fonte"] if texto and texto["status"] == "ok" else None
    r = montar(arquivos, fonte_texto)
    pedidos = r.pop("_reler")
    if pedidos and config is not None:
        r = montar(_reler(arquivos, pedidos, config), fonte_texto)
        r.pop("_reler")
    if texto:
        r["documentos"].append({k: texto[k] for k in ("arquivo", "status", "erro", "inclui") if k in texto})
        if texto["status"] != "ok":
            r["alertas"].append({"campo": None, "tipo": "aviso", "arquivo": "texto",
                                 "mensagem": "o texto não foi lido; os dados dele estão faltando"})
    r["resultado"] = "alerta" if r["alertas"] else "ok"
    return r
