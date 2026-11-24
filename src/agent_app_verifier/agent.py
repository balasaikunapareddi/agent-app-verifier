"""Agent loop: build a spec from a plain-language request, drive it,
read the failures, fix the spec, re-verify until the scripted test passes.

The loop is deliberately framework-free: the driver loop IS the product.
The model only ever writes YAML specs (one fenced block); everything else
— serving, driving, screenshotting, testing — is deterministic code, so a
failure report is ground truth the model can act on, not a vibe.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

from .driver import AppDriver
from .prompts import FIX_PROMPT, SYSTEM_PROMPT
from .scripted import TestReport, run_scripted_test
from .spec import AppSpec, SpecError

DEFAULT_MODEL = "gemini/gemini-3.5-flash-lite"
_YAML_BLOCK = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)```", re.DOTALL)


class AppVerifierAgent:
    """Builds an app from a request and verifies it with the driver.

    ``llm_call`` is a callable ``(messages) -> str`` returning the model's
    raw reply. By default it calls LiteLLM with ``LLM_MODEL`` (or
    ``gemini/gemini-3.5-flash-lite``). Tests inject a stub.
    """

    def __init__(self, model: str | None = None,
                 llm_call: Callable[[list[dict[str, str]]], str] | None = None,
                 workdir: str | Path = "."):
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.llm_call = llm_call or self._default_llm_call
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)

    # -- LLM -----------------------------------------------------------
    def _default_llm_call(self, messages: list[dict[str, str]]) -> str:
        import litellm

        response = litellm.completion(model=self.model, messages=messages)
        return response.choices[0].message.content or ""

    # -- spec extraction ------------------------------------------------
    @staticmethod
    def extract_spec_yaml(reply: str) -> str:
        match = _YAML_BLOCK.search(reply)
        if match:
            return match.group(1).strip()
        return reply.strip()

    # -- the loop -------------------------------------------------------
    def build_and_verify(self, request: str, test_path: str | Path,
                         max_attempts: int = 3) -> dict[str, Any]:
        """Run the build → drive → fix loop. Returns a structured report."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request},
        ]
        attempts: list[dict[str, Any]] = []
        last_spec_yaml = ""

        for attempt in range(1, max_attempts + 1):
            reply = self.llm_call(messages)
            last_spec_yaml = self.extract_spec_yaml(reply)
            attempt_info: dict[str, Any] = {"attempt": attempt}
            try:
                spec = AppSpec.from_yaml(last_spec_yaml)
            except SpecError as exc:
                attempt_info["error"] = f"spec invalid: {exc}"
                attempts.append(attempt_info)
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": FIX_PROMPT.format(
                    failures=f"The spec failed to parse: {exc}")})
                continue

            driver = AppDriver(spec, workdir=self.workdir / f"attempt-{attempt}")
            report = run_scripted_test(driver, test_path)
            attempt_info["test"] = report.to_dict()
            attempts.append(attempt_info)
            if report.passed:
                return {
                    "status": "passed",
                    "request": request,
                    "model": self.model,
                    "attempts": attempts,
                    "attempts_used": attempt,
                    "spec_yaml": last_spec_yaml,
                    "final_state": driver.state(),
                }
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": FIX_PROMPT.format(
                failures="\n".join(
                    f"- step {f.step} ({f.op}): {f.detail}" for f in report.failures))})

        return {
            "status": "failed",
            "request": request,
            "model": self.model,
            "attempts": attempts,
            "attempts_used": max_attempts,
            "spec_yaml": last_spec_yaml,
        }
