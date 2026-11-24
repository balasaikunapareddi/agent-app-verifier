"""Live test: run the real agent loop once against a live model.

Run with the Gemini key harness (never print the key):

    python3 ~/workspace/custom-connectors/custom.gemini/bin/run_live.py \
        ~/workspace/agent-app-verifier/.venv/bin/python \
        scripts/live_test.py

Model comes from LLM_MODEL (default gemini/gemini-3.5-flash-lite).
Exits 0 only if the agent builds a spec and the scripted test passes.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_app_verifier.agent import AppVerifierAgent  # noqa: E402
from agent_app_verifier.cli import DEMO_REQUEST  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEMO_TEST = PROJECT_DIR / "examples" / "todo-demo.yaml"


def main() -> int:
    model = os.environ.get("LLM_MODEL", "gemini/gemini-3.5-flash-lite")
    print(f"[live] model={model}")
    workdir = PROJECT_DIR / ".runs" / "live"
    agent = AppVerifierAgent(model=model, workdir=workdir)
    report = agent.build_and_verify(DEMO_REQUEST, DEMO_TEST, max_attempts=3)
    print(json.dumps(report, indent=2, default=str))
    if report["status"] == "passed":
        print(f"[live] LIVE TEST PASSED in {report['attempts_used']} attempt(s)")
        return 0
    print("[live] LIVE TEST FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
