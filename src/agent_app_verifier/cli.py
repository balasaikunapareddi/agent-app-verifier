"""CLI for agent-app-verifier.

    python -m agent_app_verifier demo     # agent builds + verifies the todo app
    python -m agent_app_verifier verify   # run the scripted test, no LLM
    python -m agent_app_verifier serve    # serve the app on http://127.0.0.1:8765/
    python -m agent_app_verifier screenshot

``demo`` uses the live LLM when an API key is configured (``GEMINI_API_KEY``
or whatever ``LLM_MODEL`` needs); without a key it falls back to the
built-in spec so the one-command demo still runs offline — the report says
which mode ran.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .agent import AppVerifierAgent
from .driver import AppDriver
from .scripted import run_scripted_test
from .spec import AppSpec

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent.parent
DEFAULT_SPEC = PROJECT_DIR / "specs" / "todo.yaml"
DEFAULT_TEST = PROJECT_DIR / "examples" / "todo-demo.yaml"

DEMO_REQUEST = (
    "Build a todo app: a title, an input to add a todo, an Add button, "
    "a list showing each todo with a checkbox to mark it done and a delete "
    "button, a line showing how many are left, and a timer showing how long "
    "ago the list was last updated."
)


def _workdir() -> Path:
    workdir = Path(os.environ.get("AAV_WORKDIR", PROJECT_DIR / ".runs"))
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def cmd_demo(args: argparse.Namespace) -> int:
    workdir = _workdir() / "demo"
    workdir.mkdir(parents=True, exist_ok=True)
    agent = AppVerifierAgent(model=args.model, workdir=workdir)

    # Serve the app while the agent works, so the loop is real end to end.
    server = _start_server(workdir, args.port)
    try:
        if _llm_available(agent.model):
            print(f"[demo] live agent loop, model={agent.model}")
            report = agent.build_and_verify(DEMO_REQUEST, DEFAULT_TEST,
                                            max_attempts=args.max_attempts)
            report["mode"] = "live-llm"
            report["served_at"] = f"http://127.0.0.1:{server.server_address[1]}/"
        else:
            print("[demo] no API key found — offline mode: built-in spec + driver verification")
            spec = AppSpec.from_file(DEFAULT_SPEC)
            driver = AppDriver(spec, workdir=workdir / "attempt-1")
            test = run_scripted_test(driver, DEFAULT_TEST)
            report = {
                "status": "passed" if test.passed else "failed",
                "mode": "offline-builtin-spec",
                "model": agent.model,
                "attempts_used": 1,
                "attempts": [{"attempt": 1, "test": test.to_dict()}],
                "final_state": driver.state(),
                "served_at": f"http://127.0.0.1:{server.server_address[1]}/",
            }
        print(json.dumps(report, indent=2, default=str))
        return 0 if report["status"] == "passed" else 1
    finally:
        server.shutdown()
        server.server_close()


def _llm_available(model: str) -> bool:
    """True when an API key for the configured model is in the environment."""
    if model.startswith("gemini/"):
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    if model.startswith("openai/"):
        return bool(os.environ.get("OPENAI_API_KEY"))
    if model.startswith("groq/"):
        return bool(os.environ.get("GROQ_API_KEY"))
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def cmd_verify(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec or DEFAULT_SPEC)
    test_path = Path(args.test or DEFAULT_TEST)
    workdir = _workdir() / "verify"
    spec = AppSpec.from_file(spec_path)
    driver = AppDriver(spec, workdir=workdir)
    report = run_scripted_test(driver, test_path)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.passed else 1


def _start_server(workdir: Path, port: int) -> ThreadingHTTPServer:
    driver = AppDriver(AppSpec.from_file(DEFAULT_SPEC), workdir=workdir)

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib name
            if self.path in ("/", "/index.html"):
                body = driver.html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404, "not found")

        def log_message(self, *a: Any) -> None:  # keep the console clean
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def cmd_serve(args: argparse.Namespace) -> int:
    server = _start_server(_workdir() / "serve", args.port)
    port = server.server_address[1]
    print(f"Serving the todo app at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.shutdown()
        server.server_close()
    return 0


def cmd_screenshot(args: argparse.Namespace) -> int:
    spec = AppSpec.from_file(Path(args.spec or DEFAULT_SPEC))
    driver = AppDriver(spec, workdir=_workdir() / "shots")
    # Pre-fill a little state so the screenshot shows something.
    driver.type("new_todo", "Buy milk")
    driver.tap("add_button")
    driver.type("new_todo", "Walk the dog")
    driver.tap("add_button")
    driver.tap("todo_list", index=0, part="toggle")
    info = driver.screenshot()
    out = Path(args.out) if args.out else Path(info["path"])
    if args.out:
        import shutil

        shutil.copyfile(info["path"], out)
        Path(info["path"]).unlink(missing_ok=True)
        info["path"] = str(out)
    print(json.dumps(info, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-app-verifier")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="agent builds + verifies the todo app")
    demo.add_argument("--model", default=None)
    demo.add_argument("--port", type=int, default=0)
    demo.add_argument("--max-attempts", type=int, default=3)
    demo.set_defaults(func=cmd_demo)

    verify = sub.add_parser("verify", help="run the scripted test, no LLM")
    verify.add_argument("--spec", default=None)
    verify.add_argument("--test", default=None)
    verify.set_defaults(func=cmd_verify)

    serve = sub.add_parser("serve", help="serve the app locally")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=cmd_serve)

    shot = sub.add_parser("screenshot", help="render a PNG of the app")
    shot.add_argument("--spec", default=None)
    shot.add_argument("--out", default=None)
    shot.set_defaults(func=cmd_screenshot)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
