import json
from datetime import datetime, timezone

import pytest

from extrator_agy.agy import ErroAgy, consultar_limites, rodar_agy


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
