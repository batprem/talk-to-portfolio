"""AI chat backend for the Efficient Frontier dashboard, powered by the Codex SDK.

The dashboard computes a portfolio; this module lets a student *ask about it* in
plain language ("why is XYZ weighted near zero?", "explain Sharpe"). We ground
the Codex thread in the current results so answers reference the real numbers on
screen, and we run in a read-only sandbox so the assistant can look but never
touch files.

Design choices worth knowing:
- The Codex SDK is agentic and beta, so every call is wrapped defensively: a
  missing package, missing credentials, or a runtime error degrades to a helpful
  message instead of crashing the dashboard.
- A Codex *thread* keeps conversation memory across turns, so we start one, prime
  it once with the portfolio context, and reuse it. When the portfolio inputs
  change (different tickers, rf, etc.) the caller starts a fresh thread.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

INSTALL_HINT = (
    "AI chat runs on the Codex SDK. To enable it:\n\n"
    "1. `pip install openai-codex` (or add `--with openai-codex` to the launch command)\n"
    "2. Authenticate — either set `CODEX_API_KEY` (OpenAI Platform key) or run `codex login`\n"
    "   to sign in with ChatGPT.\n\n"
    "The dashboard works fully without it; chat is an optional extra."
)

SYSTEM_PRIMER = (
    "You are a concise finance assistant embedded in an Efficient Frontier dashboard "
    "used by Thai finance/accounting students who are new to coding. You can BOTH explain "
    "the portfolio AND change the dashboard's inputs on the user's behalf.\n\n"
    "You are in a read-only sandbox: never modify files, only read to answer.\n\n"
    "PROTOCOL — for EVERY user message reply with ONE JSON object and nothing else:\n"
    '{"action": "update" | "answer", "updates": {...}, "reply": "<short message>"}\n\n'
    "Use action=\"update\" when the user asks to change any dashboard input; put ONLY the "
    "changed inputs in `updates`. Otherwise use action=\"answer\" with updates={} and put your "
    "explanation in `reply`. Explain concepts (Sharpe ratio, diversification, min-variance vs "
    "max-Sharpe, correlation) simply when asked. Always write `reply` in the same language the "
    "user writes in (Thai or English).\n\n"
    "Controllable inputs (keys allowed in `updates`, with valid values):\n"
    '  "source": "online" or "offline"\n'
    '  "tickers": array of symbols, e.g. ["PTT.BK","KBANK.BK"] (offline dataset only has "ABC","XYZ")\n'
    '  "rf": risk-free rate as a fraction, e.g. 0.05 for 5%\n'
    '  "period": one of "1y","2y","3y","5y","10y" (online lookback)\n'
    '  "n_portfolios": integer 1000..20000 (# simulated portfolios)\n'
    '  "weight_cap": max weight per asset as a fraction 0.1..1.0, or null to remove the cap\n'
    '  "seed": integer random seed\n\n'
    "Examples:\n"
    'User: "set risk-free rate to 5% and use PTT.BK, KBANK.BK" -> '
    '{"action":"update","updates":{"rf":0.05,"tickers":["PTT.BK","KBANK.BK"]},'
    '"reply":"ปรับ risk-free rate เป็น 5% และใช้ PTT.BK, KBANK.BK แล้วครับ"}\n'
    'User: "why is the frontier curved?" -> '
    '{"action":"answer","updates":{},"reply":"เพราะสินทรัพย์ไม่ได้เคลื่อนไหวไปทางเดียวกัน..."}\n\n'
    "Portfolio context:\n\n{context}"
)

# Logical input fields the chat may change, with their valid ranges/options. Kept here (not in
# app.py) so chat.py owns the schema; app.py maps these logical names to Streamlit widget keys.
ALLOWED_PERIODS = ("1y", "2y", "3y", "5y", "10y")
N_PORTFOLIOS_RANGE = (1000, 20000)
WEIGHT_CAP_RANGE = (0.1, 1.0)


def codex_status() -> tuple[bool, str]:
    """Return (usable, message). usable=False means show INSTALL_HINT instead of chat."""
    try:
        import openai_codex  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        return False, INSTALL_HINT
    if os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return True, "Codex ready (API key)."
    # ChatGPT login (`codex login`) may still authenticate; we can't cheaply verify
    # it here, so allow it but flag the likely failure mode.
    return True, (
        "Codex SDK installed. No CODEX_API_KEY/OPENAI_API_KEY found — relying on "
        "`codex login` (ChatGPT). Set an API key if chat errors out."
    )


def portfolio_context(res: dict) -> str:
    """Compact, numbers-first summary of the current dashboard result for priming."""
    stats, optima, assets = res["stats"], res["optima"], res["stats"]["tickers"]
    lines = [
        f"Data source: {res['source_used']}; risk-free rate: {res['rf']:.2%}.",
        f"Assets: {', '.join(assets)}.",
        "Per-asset annualized (return / volatility / Sharpe):",
    ]
    for a in assets:
        lines.append(
            f"  {a}: {stats['ann_return'][a]:.2%} / {stats['ann_vol'][a]:.2%} / {res['asset_sharpe'][a]:.2f}"
        )
    for label in ("min_variance", "max_sharpe"):
        row = optima[label]
        w = row[assets]
        weights = ", ".join(f"{a} {w[a]:.1%}" for a in assets)
        lines.append(
            f"{label}: return {row['return']:.2%}, volatility {row['volatility']:.2%}, "
            f"Sharpe {row['sharpe']:.2f}; weights: {weights}"
        )
    return "\n".join(lines)


def start_thread(context: str, cwd: str | None = None):
    """Create a Codex client + thread primed with the portfolio context.

    Returns (client, thread). Keep both alive (e.g. in st.session_state) so the
    thread's conversation memory persists across questions. The client is NOT used
    as a context manager on purpose — a Streamlit session outlives one call.
    """
    from openai_codex import Codex, Sandbox

    codex = Codex()
    # Don't pin a model — use the account's default so this works regardless of
    # which Codex models the user has access to.
    kwargs = {"sandbox": Sandbox.read_only}
    if cwd:
        kwargs["cwd"] = cwd
    try:
        thread = codex.thread_start(**kwargs)
    except TypeError:
        # Older/newer beta signatures may not accept cwd; retry minimally.
        thread = codex.thread_start(sandbox=Sandbox.read_only)
    # Use replace, not str.format — SYSTEM_PRIMER contains literal JSON braces
    # ({"action": ...}) that .format() would misread as replacement fields.
    thread.run(SYSTEM_PRIMER.replace("{context}", context))  # prime; ignore the ack
    return codex, thread


def ask(thread, question: str) -> str:
    """Send a user question to the primed thread and return the text answer."""
    result = thread.run(question)
    return getattr(result, "final_response", None) or str(result)


def _extract_json(text: str) -> dict | None:
    """Best-effort pull of a single JSON object out of the model's reply.

    Tries the whole string, then a ```json fenced block, then the first balanced
    ``{...}`` span. Returns None if nothing parses.
    """
    for candidate in _json_candidates(text):
        try:
            obj = json.loads(candidate)
        except (ValueError, TypeError):
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


def _validate_updates(raw: dict) -> dict:
    """Coerce and clamp the model's requested input changes to safe values.

    Returns a dict of *logical* fields (app.py maps them to widget keys). Unknown or
    unparseable fields are dropped. Clamping is required: setting a slider/selectbox
    session_state value out of range/options raises when the widget is built.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}

    src = raw.get("source")
    if isinstance(src, str) and src.strip().lower() in ("online", "offline"):
        out["source"] = src.strip().lower()

    if "tickers" in raw:
        tickers = raw["tickers"]
        if isinstance(tickers, str):
            parts = [t.strip() for t in tickers.split(",") if t.strip()]
        elif isinstance(tickers, (list, tuple)):
            parts = [str(t).strip() for t in tickers if str(t).strip()]
        else:
            parts = []
        if parts:
            out["tickers"] = parts

    if "rf" in raw:
        try:
            rf = float(raw["rf"])
            if rf > 1:  # user/model gave a percent (e.g. 5 meaning 5%)
                rf /= 100.0
            out["rf"] = max(0.0, rf)
        except (ValueError, TypeError):
            pass

    period = raw.get("period")
    if isinstance(period, str) and period.strip().lower() in ALLOWED_PERIODS:
        out["period"] = period.strip().lower()

    if "n_portfolios" in raw:
        try:
            n = int(round(float(raw["n_portfolios"])))
            lo, hi = N_PORTFOLIOS_RANGE
            out["n_portfolios"] = max(lo, min(hi, n))
        except (ValueError, TypeError):
            pass

    if "weight_cap" in raw:
        wc = raw["weight_cap"]
        if wc is None or (isinstance(wc, str) and wc.strip().lower() in ("off", "none", "")) or wc == 0:
            out["weight_cap"] = None  # remove the cap
        else:
            try:
                cap = float(wc)
                lo, hi = WEIGHT_CAP_RANGE
                out["weight_cap"] = max(lo, min(hi, cap))
            except (ValueError, TypeError):
                pass

    if "seed" in raw:
        try:
            out["seed"] = int(round(float(raw["seed"])))
        except (ValueError, TypeError):
            pass

    return out


# Logical field (from interpret) -> the app's Streamlit widget session_state key.
LOGICAL_TO_KEY = {
    "source": "ef_source",
    "rf": "ef_rf",
    "period": "ef_period",
    "n_portfolios": "ef_n_portfolios",
    "seed": "ef_seed",
}


def to_widget_updates(updates: dict) -> tuple[dict, list[str]]:
    """Map validated logical updates to {widget_key: value} plus a human-readable note list.

    Kept next to the schema so the whole chat→UI contract lives in one module (and is
    unit-testable without Streamlit). `tickers` joins to a CSV string; `weight_cap`
    toggles the cap checkbox; the rest map straight through LOGICAL_TO_KEY.
    """
    pending: dict = {}
    notes: list[str] = []
    for field, value in updates.items():
        if field == "tickers":
            csv = ", ".join(value) if isinstance(value, (list, tuple)) else str(value)
            pending["ef_tickers_raw"] = csv
            notes.append(f"tickers → {csv}")
        elif field == "weight_cap":
            if value is None:
                pending["ef_cap_on"] = False
                notes.append("weight cap → off")
            else:
                pending["ef_cap_on"] = True
                pending["ef_weight_cap"] = value
                notes.append(f"weight cap → {value:.0%}")
        elif field == "rf":
            pending["ef_rf"] = value
            notes.append(f"rf → {value:.1%}")
        elif field in LOGICAL_TO_KEY:
            pending[LOGICAL_TO_KEY[field]] = value
            notes.append(f"{field} → {value}")
    return pending, notes


def interpret_via_subprocess(
    context: str,
    question: str,
    history: list[dict] | None = None,
    cwd: str | None = None,
    timeout: float = 150.0,
) -> dict:
    """Run the Codex round-trip in an isolated worker process and return its action.

    Calling the Codex SDK directly inside Streamlit hard-crashes the whole server
    (uncatchable). Shelling out to `chat_worker.py` isolates that: a crash there
    only kills the child, and we surface it as a normal exception the caller renders
    gracefully. Returns the same ``{action, reply, updates}`` dict as `interpret`.
    """
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_worker.py")
    payload = json.dumps(
        {"context": context, "question": question, "history": history or [], "cwd": cwd}
    )
    proc = subprocess.run(
        [sys.executable, worker],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout,
        # Critical: put the worker (and everything Codex spawns underneath it — the
        # node app-server, sandbox-exec children) in its OWN session. Otherwise they
        # share our process group, and Codex's sandbox machinery signals that group,
        # which kills the parent Streamlit server. This isolation is what makes chat
        # survivable inside Streamlit.
        start_new_session=True,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (proc.stderr or "").strip()
        raise RuntimeError(
            f"chat worker exited {proc.returncode} without a result: "
            f"{err[-600:] if err else 'no stderr'}"
        )
    try:
        result = json.loads(out)
    except ValueError as exc:
        raise RuntimeError(f"chat worker returned non-JSON: {out[:300]!r}") from exc
    # Defensive: guarantee the contract even if the worker was tampered with.
    result.setdefault("action", "answer")
    result.setdefault("reply", "")
    result.setdefault("updates", {})
    return result


def interpret(thread, question: str) -> dict:
    """Send a message and return a structured action.

    Returns ``{"action": "update"|"answer", "reply": str, "updates": dict}``. The model
    is primed (see SYSTEM_PRIMER) to answer with a JSON object; if it doesn't, we degrade
    to a plain ``answer`` carrying the raw text so chat still works.
    """
    result = thread.run(question)
    text = getattr(result, "final_response", None) or str(result)

    obj = _extract_json(text)
    if obj is None:
        return {"action": "answer", "reply": text, "updates": {}}

    updates = _validate_updates(obj.get("updates") or {})
    reply = obj.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        reply = text if not updates else "อัปเดตค่าให้แล้วครับ / Updated the inputs."
    action = "update" if (obj.get("action") == "update" and updates) else "answer"
    return {"action": action, "reply": reply, "updates": updates}
