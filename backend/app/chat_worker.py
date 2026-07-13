"""Out-of-process Codex worker for /api/chat."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openai_codex import Codex, Sandbox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chat import SYSTEM_PRIMER, interpret_response


def main() -> None:
    request = json.load(sys.stdin)
    context = request["context"]
    history = request.get("history") or []
    if history:
        recent = "\n".join(f"{item['role']}: {item['content']}" for item in history[-6:])
        context = f"{context}\n\nRecent conversation:\n{recent}"

    codex = Codex()
    thread = codex.thread_start(sandbox=Sandbox.read_only)
    thread.run(SYSTEM_PRIMER.replace("{context}", context))
    result = thread.run(request["question"])
    text = getattr(result, "final_response", None) or str(result)
    sys.stdout.write(json.dumps(interpret_response(text)))


if __name__ == "__main__":
    main()
