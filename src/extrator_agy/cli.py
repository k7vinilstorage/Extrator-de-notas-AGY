"""Linha de comando: processa uma pasta de notas e grava um JSON por nota."""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import __version__
from .agy import MODELO_PADRAO, ErroAgy
from .extracao import CAMPOS, Config, processar

EXTENSOES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def listar_arquivos(entradas: list[Path], recursivo: bool) -> list[tuple[Path, Path]]:
    """Retorna pares (arquivo, caminho relativo usado para nomear a saída)."""
    arquivos = []
    for entrada in entradas:
        if entrada.is_file():
            arquivos.append((entrada, Path(entrada.name)))
        elif entrada.is_dir():
            padrao = entrada.rglob("*") if recursivo else entrada.glob("*")
            arquivos += [
                (a, a.relative_to(entrada))
                for a in sorted(padrao)
                if a.is_file() and a.suffix.lower() in EXTENSOES
            ]
        else:
            print(f"aviso: {entrada} não existe", file=sys.stderr)
    return arquivos


def caminho_saida(saida: Path, relativo: Path) -> Path:
    # Mantém a extensão no nome para foto.jpg e foto.pdf não colidirem.
    return saida / relativo.with_name(relativo.name + ".json")


def ja_processado(destino: Path) -> bool:
    """Só conta como processado se o JSON existente estiver no formato atual."""
    try:
        return list(json.loads(destino.read_text(encoding="utf-8"))) == CAMPOS
    except (OSError, ValueError):
        return False


def gravar(arquivo: Path, destino: Path, config: Config):
    resultado = processar(arquivo, config)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".tmp")
    temporario.write_text(json.dumps(resultado.nota, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(destino)
    return resultado


def resumo(nota: dict) -> str:
    total = nota.get("valor_total")
    valor = f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if total is not None else "R$ ?"
    return f"{nota.get('razao_social') or '?'} · {valor} · {nota.get('categoria_gasto')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="extrator",
        description="Extrai dados de notas e cupons fiscais (fotos e PDFs) usando a agy CLI.",
    )
    parser.add_argument("entradas", nargs="+", type=Path, help="pastas ou arquivos (jpg, png, webp, pdf)")
    parser.add_argument("-o", "--saida", type=Path, default=Path("saida"), help="pasta dos JSONs (padrão: saida)")
    parser.add_argument("-m", "--modelo", default=MODELO_PADRAO, help=f"modelo do agy (padrão: {MODELO_PADRAO})")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="notas processadas em paralelo (padrão: 4)")
    parser.add_argument("-r", "--recursivo", action="store_true", help="inclui subpastas")
    parser.add_argument("-f", "--forcar", action="store_true", help="reprocessa notas que já têm JSON")
    parser.add_argument("--sem-revisao", action="store_true",
                        help="não relê as notas que falharem na validação (mais rápido, menos preciso)")
    parser.add_argument("--timeout", type=int, default=90, help="segundos por chamada do agy (padrão: 90)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    pendentes, pulados = [], 0
    for arquivo, relativo in listar_arquivos(args.entradas, args.recursivo):
        destino = caminho_saida(args.saida, relativo)
        if ja_processado(destino) and not args.forcar:
            pulados += 1
        else:
            pendentes.append((arquivo, destino))

    if pulados:
        print(f"{pulados} nota(s) já processada(s), pulando (use --forcar para refazer)")
    if not pendentes:
        print("nada a processar")
        return 0
    print(f"processando {len(pendentes)} nota(s) com {args.modelo}...\n")

    config = Config(modelo=args.modelo, timeout_s=args.timeout, revisar=not args.sem_revisao)
    ok = alertas = erros = 0
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        tarefas = {pool.submit(gravar, arquivo, destino, config): arquivo for arquivo, destino in pendentes}
        for tarefa in as_completed(tarefas):
            arquivo = tarefas[tarefa]
            try:
                r = tarefa.result()
            except ErroAgy as e:
                erros += 1
                print(f"✗ {arquivo.name}: {e}")
                continue
            if r.problemas:
                alertas += 1
                print(f"⚠ {arquivo.name}: {resumo(r.nota)} [chave: {r.origem_chave}]")
                for p in r.problemas:
                    print(f"    - {p}")
            else:
                ok += 1
                print(f"✓ {arquivo.name}: {resumo(r.nota)} [chave: {r.origem_chave}]")

    print(f"\n{ok} ok, {alertas} com alertas, {erros} com erro → {args.saida}/")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
