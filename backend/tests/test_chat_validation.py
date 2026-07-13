import subprocess

from fastapi.testclient import TestClient

from app.chat import codex_status, run_codex_chat, run_codex_cli_chat, validate_updates
from app.main import app


client = TestClient(app)


def test_validate_updates_clamps_and_drops_invalid_values():
    updates = validate_updates(
        {
            "source": "ONLINE",
            "tickers": "abc, xyz",
            "rf": 5,
            "period": "99y",
            "n_portfolios": 999999,
            "weight_cap": 80,
            "seed": "12.7",
            "unknown": "ignored",
        }
    )

    assert updates == {
        "source": "online",
        "tickers": ["ABC", "XYZ"],
        "rf": 0.05,
        "n_portfolios": 20000,
        "weight_cap": 0.8,
        "seed": 13,
    }


def test_validate_updates_can_remove_weight_cap():
    assert validate_updates({"weight_cap": "off"}) == {"weight_cap": None}


def test_chat_endpoint_degrades_when_codex_unavailable(monkeypatch):
    monkeypatch.setattr("app.chat.codex_status", lambda: (False, "chat unavailable"))

    response = client.post("/api/chat", json={"message": "explain max Sharpe"})

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "status": "unavailable",
        "action": "answer",
        "reply": "chat unavailable",
        "updates": {},
    }


def test_codex_status_uses_cli_when_sdk_is_unavailable(monkeypatch):
    monkeypatch.setattr("app.chat._codex_sdk_available", lambda: False)
    monkeypatch.setattr("app.chat._codex_cli_path", lambda: "/usr/local/bin/codex")

    available, message = codex_status()

    assert available is True
    assert message == "Codex CLI chat is available."


def test_run_codex_chat_falls_back_to_cli(monkeypatch):
    calls = []

    def fake_cli_chat(**kwargs):
        calls.append(kwargs)
        return {"action": "answer", "reply": "via cli", "updates": {}}

    monkeypatch.setattr("app.chat._codex_sdk_available", lambda: False)
    monkeypatch.setattr("app.chat._codex_cli_path", lambda: "/usr/local/bin/codex")
    monkeypatch.setattr("app.chat.run_codex_cli_chat", fake_cli_chat)

    result = run_codex_chat(
        context="Assets: ABC, XYZ.",
        question="explain max Sharpe",
        history=[{"role": "user", "content": "hello"}],
        timeout=3,
    )

    assert result == {"action": "answer", "reply": "via cli", "updates": {}}
    assert calls == [
        {
            "context": "Assets: ABC, XYZ.",
            "question": "explain max Sharpe",
            "history": [{"role": "user", "content": "hello"}],
            "cli_path": "/usr/local/bin/codex",
            "timeout": 3,
        }
    ]


def test_run_codex_cli_chat_invokes_codex_exec_and_parses_response(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append({"args": args, **kwargs})
        output_path = args[args.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(
                '{"action":"update","updates":{"tickers":"abc, xyz","rf":5},'
                '"reply":"Updated."}'
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.chat.subprocess.run", fake_run)

    result = run_codex_cli_chat(
        context="Assets: ABC, XYZ.",
        question="set rf to 5%",
        history=[{"role": "assistant", "content": "Current rf is 2%."}],
        cli_path="/usr/local/bin/codex",
        timeout=7,
    )

    assert result == {
        "action": "update",
        "reply": "Updated.",
        "updates": {"tickers": ["ABC", "XYZ"], "rf": 0.05},
    }
    call = calls[0]
    assert call["args"][:2] == ["/usr/local/bin/codex", "exec"]
    assert "--sandbox" in call["args"]
    assert "read-only" in call["args"]
    assert "--ask-for-approval" in call["args"]
    assert "never" in call["args"]
    assert "--ephemeral" in call["args"]
    assert "--output-schema" in call["args"]
    assert call["args"][-1] == "-"
    assert call["input"].count("Assets: ABC, XYZ.") == 1
    assert "assistant: Current rf is 2%." in call["input"]
    assert "User message:\nset rf to 5%" in call["input"]
    assert call["capture_output"] is True
    assert call["text"] is True
    assert call["timeout"] == 7
    assert call["start_new_session"] is True
