import json
from datetime import datetime, timezone

import pytest

from extrator_agy.agy import ErroAgy, consultar_limites, extrair, rodar_agy, transcrever
from extrator_agy.schema import NOTA


@pytest.fixture
def agy_falso(tmp_path, monkeypatch):
    """Põe no PATH um `agy` que imprime a saída e o stderr dados."""
    def criar(saida: dict, stderr: str = ""):
        script = tmp_path / "agy"
        script.write_text(f"#!/bin/sh\ncat <<'FIM'\n{json.dumps(saida)}\nFIM\ncat >&2 <<'FIM'\n{stderr}\nFIM\n")
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    return criar


def test_resposta_ok(agy_falso, tmp_path):
    agy_falso({"status": "SUCCESS", "response": "{}", "structured_output": {}})
    assert rodar_agy([], cwd=str(tmp_path), timeout_s=5)["structured_output"] == {}


def test_print_timeout_vira_erro(agy_falso, tmp_path):
    # Estourado o --print-timeout, o agy sai com SUCCESS e resposta vazia.
    agy_falso({"status": "SUCCESS", "response": ""},
              "[agy] print timeout after 90s with turn in progress; returning partial output")
    with pytest.raises(ErroAgy, match="não respondeu em 90s"):
        rodar_agy([], cwd=str(tmp_path), timeout_s=90)


def test_comando_negado_vira_erro(agy_falso, tmp_path):
    agy_falso({"status": "SUCCESS", "response": ""},
              'jetski: no output produced — a tool required the "command" permission that headless mode '
              "cannot prompt for, so it was auto-denied.")
    with pytest.raises(ErroAgy, match="sem resposta: .*command"):
        rodar_agy([], cwd=str(tmp_path), timeout_s=5)


USAGE = {
    "status": "SUCCESS", "response": "Gemini Models\tWeekly Limit Remaining\t45%\n",
    "command": {"name": "usage", "data": {"groups": [
        {"name": "Gemini Models", "buckets": [
            {"id": "gemini-weekly", "window": "weekly", "remaining_fraction": 0.44731, "reset_time": "2026-10-25T23:49:04Z"},
            {"id": "gemini-5h", "window": "5h", "remaining_fraction": 0.91481, "reset_time": "2026-10-21T22:01:14Z"},
        ]},
        {"name": "Claude and GPT models", "buckets": [
            {"id": "3p-weekly", "window": "weekly", "remaining_fraction": 1, "reset_time": "2026-10-28T18:02:26Z"},
        ]},
    ]}},
}


def test_consultar_limites(agy_falso):
    agy_falso(USAGE)
    limites = consultar_limites()
    assert limites["semanal"]["restante_pct"] == 44.7
    assert limites["cinco_horas"]["restante_pct"] == 91.5
    renova = datetime.fromisoformat(limites["semanal"]["renova_em"])
    assert renova == datetime(2026, 10, 25, 23, 49, 4, tzinfo=timezone.utc)


def test_consultar_limites_sem_a_cota_gemini(agy_falso):
    agy_falso(USAGE | {"command": {"name": "usage", "data": {"groups": []}}})
    with pytest.raises(ErroAgy, match="resposta inesperada"):
        consultar_limites()


def test_consultar_limites_servico_fora(agy_falso):
    agy_falso({"status": "ERROR", "response": "", "error": "/usage failed: UNAVAILABLE (code 503)"})
    with pytest.raises(ErroAgy, match="UNAVAILABLE"):
        consultar_limites()


@pytest.fixture
def agy_que_anota(tmp_path, monkeypatch):
    """`agy` que guarda os argumentos recebidos e responde com o structured_output dado."""
    def criar(structured_output: dict):
        args = tmp_path / "args.txt"
        saida = {"status": "SUCCESS", "response": "{}", "structured_output": structured_output}
        script = tmp_path / "agy"
        script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {args}\ncat <<'FIM'\n{json.dumps(saida)}\nFIM\n")
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
        return args
    return criar


def test_transcrever_copia_os_arquivos_e_troca_o_marcador(agy_que_anota, tmp_path):
    args = agy_que_anota({"ok": True})
    (tmp_path / "info.txt").write_text("x")
    assert transcrever([tmp_path / "info.txt"], "Leia {arquivos}.", {"type": "object"}) == {"ok": True}
    linhas = args.read_text().splitlines()
    prompt = linhas[linhas.index("--print") + 1]
    assert prompt.startswith("Leia /") and prompt.endswith("/documento.txt.")
    assert "--log-file" not in linhas


def test_transcrever_com_log_temporario(agy_que_anota, tmp_path):
    args = agy_que_anota({})
    (tmp_path / "a.png").write_bytes(b"x")
    transcrever([tmp_path / "a.png"], "{arquivos}", {}, log_temporario=True)
    linhas = args.read_text().splitlines()
    pasta = linhas[linhas.index("--add-dir") + 1]
    assert linhas[linhas.index("--log-file") + 1] == f"{pasta}/agy.log"


def test_extrair_continua_igual(agy_que_anota, tmp_path):
    args = agy_que_anota({"cpf_cnpj": None})
    for nome in ("p1.png", "p2.png"):
        (tmp_path / nome).write_bytes(b"x")
    assert extrair([tmp_path / "p1.png", tmp_path / "p2.png"], chave_qr="1" * 44) == {"cpf_cnpj": None}
    linhas = args.read_text().splitlines()
    prompt = "\n".join(linhas[linhas.index("--print") + 1:linhas.index("--add-dir")])
    assert "/documento-1.png, /" in prompt and "combustivel" in prompt and "1" * 44 in prompt
    assert json.loads(linhas[linhas.index("--json-schema") + 1]) == NOTA
