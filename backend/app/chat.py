"""Optional Codex-backed chat interpretation for the Efficient Frontier API."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

INSTALL_HINT = (
    "AI chat is unavailable. To enable it, install the optional openai-codex "
    "package and set CODEX_API_KEY or OPENAI_API_KEY, or install and authenticate "
    "the Codex CLI. The frontier API works without chat."
)

SYSTEM_PRIMER = (
    "You are a concise finance assistant embedded in an Efficient Frontier app. "
    "You can explain the current portfolio and change app inputs. Reply to every "
    "user message with one JSON object only: "
    '{"action":"update"|"answer","updates":{...},"reply":"<short message>"}. '
    "Allowed update keys: source online/offline, tickers array, rf fraction, "
    "period one of 1y/2y/3y/5y/10y, n_portfolios integer 1000..20000, "
    "weight_cap fraction 0.1..1.0 or null, seed integer. Match the user's "
    "language.\n\nPortfolio context:\n\n{context}"
)

ALLOWED_PERIODS = ("1y", "2y", "3y", "5y", "10y")
N_PORTFOLIOS_RANGE = (1000, 20000)
WEIGHT_CAP_RANGE = (0.1, 1.0)


def codex_status() -> tuple[bool, str]:
    """Return whether chat can attempt a Codex SDK or CLI call."""
    if _codex_sdk_available():
        return True, "Codex SDK chat is available."
    if _codex_cli_path():
        return True, "Codex CLI chat is available."
    return False, INSTALL_HINT


def _codex_sdk_available() -> bool:
    try:
        import openai_codex  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means unavailable.
        return False
    if not (os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        return False
    return True


def _codex_cli_path() -> str | None:
    return shutil.which("codex")


def portfolio_context(frontier_result: dict[str, Any]) -> str:
    """Compact current-result summary for the chat model."""
    stats = frontier_result["stats"]
    optima = frontier_result["optima"]
    assets = stats["tickers"]
    lines = [
        f"Data source: {frontier_result['source_used']}; risk-free rate: {frontier_result['rf']:.2%}.",
        f"Assets: {', '.join(assets)}.",
        "Per-asset annualized return / volatility / Sharpe:",
    ]
    for asset in assets:
        lines.append(
            f"{asset}: {stats['ann_return'][asset]:.2%} / "
            f"{stats['ann_vol'][asset]:.2%} / {frontier_result['asset_sharpe'][asset]:.2f}"
        )
    for label in ("min_variance", "max_sharpe"):
        row = optima[label]
        weights = ", ".join(f"{asset} {row[asset]:.1%}" for asset in assets)
        lines.append(
            f"{label}: return {row['return']:.2%}, volatility {row['volatility']:.2%}, "
            f"Sharpe {row['sharpe']:.2f}; weights: {weights}"
        )
    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any] | None:
    for candidate in _json_candidates(text):
        try:
            obj = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _json_candidates(text: str):
    text = (text or "").strip()
    if not text:
        return
    yield text
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        yield fenced.group(1)
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : i + 1]
                    break


def validate_updates(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce and clamp model-requested app input changes."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}

    source = raw.get("source")
    if isinstance(source, str) and source.strip().lower() in ("online", "offline"):
        out["source"] = source.strip().lower()

    if "tickers" in raw:
        tickers = raw["tickers"]
        if isinstance(tickers, str):
            parts = [ticker.strip().upper() for ticker in tickers.split(",") if ticker.strip()]
        elif isinstance(tickers, (list, tuple)):
            parts = [str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()]
        else:
            parts = []
        if parts:
            out["tickers"] = parts[:20]

    if "rf" in raw:
        try:
            rf = float(raw["rf"])
            if rf > 1:
                rf /= 100.0
            out["rf"] = max(0.0, min(1.0, rf))
        except (TypeError, ValueError):
            pass

    period = raw.get("period")
    if isinstance(period, str) and period.strip().lower() in ALLOWED_PERIODS:
        out["period"] = period.strip().lower()

    if "n_portfolios" in raw:
        try:
            value = int(round(float(raw["n_portfolios"])))
            lo, hi = N_PORTFOLIOS_RANGE
            out["n_portfolios"] = max(lo, min(hi, value))
        except (TypeError, ValueError):
            pass

    if "weight_cap" in raw:
        weight_cap = raw["weight_cap"]
        if (
            weight_cap is None
            or weight_cap == 0
            or (isinstance(weight_cap, str) and weight_cap.strip().lower() in ("", "off", "none", "null"))
        ):
            out["weight_cap"] = None
        else:
            try:
                cap = float(weight_cap)
                if cap > 1:
                    cap /= 100.0
                lo, hi = WEIGHT_CAP_RANGE
                out["weight_cap"] = max(lo, min(hi, cap))
            except (TypeError, ValueError):
                pass

    if "seed" in raw:
        try:
            out["seed"] = int(round(float(raw["seed"])))
        except (TypeError, ValueError):
            pass

    return out


def interpret_response(text: str) -> dict[str, Any]:
    """Parse and validate a model response into the API chat contract."""
    obj = _extract_json(text)
    if obj is None:
        return {"action": "answer", "reply": text, "updates": {}}

    updates = validate_updates(obj.get("updates") or {})
    reply = obj.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        reply = text if not updates else "Updated the inputs."
    action = "update" if obj.get("action") == "update" and updates else "answer"
    return {"action": action, "reply": reply, "updates": updates}


def run_codex_chat(
    context: str,
    question: str,
    history: list[dict[str, str]] | None = None,
    timeout: float = 150.0,
) -> dict[str, Any]:
    """Run chat through the best available local Codex provider."""
    if _codex_sdk_available():
        return run_codex_sdk_chat(
            context=context,
            question=question,
            history=history,
            timeout=timeout,
        )

    cli_path = _codex_cli_path()
    if cli_path:
        return run_codex_cli_chat(
            context=context,
            question=question,
            history=history,
            cli_path=cli_path,
            timeout=timeout,
        )

    raise RuntimeError(INSTALL_HINT)


def run_codex_sdk_chat(
    context: str,
    question: str,
    history: list[dict[str, str]] | None = None,
    timeout: float = 150.0,
) -> dict[str, Any]:
    """Run the Codex SDK in an isolated worker process."""
    worker = Path(__file__).with_name("chat_worker.py")
    payload = json.dumps({"context": context, "question": question, "history": history or []})
    proc = subprocess.run(
        [sys.executable, str(worker)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout,
        start_new_session=True,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or "").strip()
        raise RuntimeError(
            f"chat worker exited {proc.returncode} without a result: "
            f"{err[-600:] if err else 'no stderr'}"
        )
    result = json.loads(out)
    return {
        "action": result.get("action", "answer"),
        "reply": result.get("reply", ""),
        "updates": validate_updates(result.get("updates") or {}),
    }


def run_codex_cli_chat(
    context: str,
    question: str,
    history: list[dict[str, str]] | None = None,
    cli_path: str = "codex",
    timeout: float = 150.0,
) -> dict[str, Any]:
    """Run Codex CLI non-interactively and parse the final response."""
    repo_root = Path(__file__).resolve().parents[2]
    prompt = _codex_cli_prompt(context=context, question=question, history=history)

    with tempfile.TemporaryDirectory(prefix="frontier-chat-") as tmpdir:
        tmp_path = Path(tmpdir)
        output_path = tmp_path / "codex-response.txt"

        proc = subprocess.run(
            [
                cli_path,
                "exec",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color",
                "never",
                "-C",
                str(repo_root),
                "--output-last-message",
                str(output_path),
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,
        )

        final_text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        if not final_text:
            final_text = (proc.stdout or "").strip()

    if proc.returncode != 0 or not final_text:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or "no output"
        raise RuntimeError(f"codex CLI exited {proc.returncode} without a result: {detail[-600:]}")

    return interpret_response(final_text)


def _codex_cli_prompt(
    context: str,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    if history:
        recent = "\n".join(
            f"{item.get('role', 'user')}: {item.get('content', '')}" for item in history[-6:]
        )
        context = f"{context}\n\nRecent conversation:\n{recent}"

    primer = SYSTEM_PRIMER.replace("{context}", context)
    return (
        f"{primer}\n\n"
        "Run as a pure chat completion. Do not inspect files, modify files, or run commands. "
        "Return the final answer as the required JSON object only.\n\n"
        f"User message:\n{question}"
    )
