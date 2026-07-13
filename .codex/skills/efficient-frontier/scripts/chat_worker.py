"""Out-of-process Codex worker for the dashboard chat.

Streamlit runs the app script inside its own runtime (worker thread + a main-thread
event loop and signal handlers). Invoking the Codex SDK *in that process* reliably
takes the whole Streamlit server down: Codex spawns a node app-server and sandbox
children, and when its sandbox tooling signals its process group that signal also
hits Streamlit (a hard exit a try/except can't catch). So `chat.py` shells out to
this script with ``start_new_session=True`` — a clean, isolated process group. If it
ever crashes, only this process dies and the dashboard shows a graceful error.

Protocol:
  stdin  : {"context": str, "question": str, "history": [{"role","content"}...], "cwd": str|null}
  stdout : {"action": "update"|"answer", "reply": str, "updates": {...}}   (the interpret() result)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chat  # noqa: E402  (sibling module)


def main() -> None:
    req = json.load(sys.stdin)
    context = req["context"]
    history = req.get("history") or []

    # Fold recent transcript into the priming context so a fresh (stateless) thread
    # still has short-term conversational continuity across messages.
    if history:
        recent = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
        context = f"{context}\n\nRecent conversation (for continuity):\n{recent}"

    _client, thread = chat.start_thread(context, cwd=req.get("cwd"))
    result = chat.interpret(thread, req["question"])
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
