"""Tests for the agent loop with a stub model (no network, no LLM)."""

from pathlib import Path

import pytest

from agent_app_verifier.agent import AppVerifierAgent
from agent_app_verifier.cli import DEMO_REQUEST

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEMO_TEST = PROJECT_DIR / "examples" / "todo-demo.yaml"
BUILTIN_SPEC = (PROJECT_DIR / "specs" / "todo.yaml").read_text(encoding="utf-8")

BROKEN_SPEC = """```yaml
app:
  title: "Todos"
components:
  - id: new_todo
    type: input
  - id: add_button
    type: button
    label: "Add"
    action: add_todo
  - id: todo_list
    type: list
    source: tasks
  - id: remaining
    type: text
    template: "{remaining} left"
  - id: updated_timer
    type: timer
    template: "updated {elapsed}s ago"
state:
  todos: []
actions:
  add_todo:
    - append: {list: todos, item: {text: "{input:new_todo}", done: false}}
    - clear: new_todo
    - touch: true
  toggle_todo:
    - toggle: {list: todos, index: "{index}"}
  delete_todo:
    - remove: {list: todos, index: "{index}"}
```
"""

GOOD_REPLY = "```yaml\n" + BUILTIN_SPEC + "\n```"


def test_extract_spec_yaml_fenced():
    agent = AppVerifierAgent(llm_call=lambda m: "")
    extracted = agent.extract_spec_yaml(GOOD_REPLY)
    assert "app:\n  title:" in extracted
    assert "```" not in extracted


def test_extract_spec_yaml_bare():
    agent = AppVerifierAgent(llm_call=lambda m: "")
    extracted = agent.extract_spec_yaml(BUILTIN_SPEC)
    assert "app:\n  title:" in extracted


def test_agent_passes_first_try(tmp_path):
    agent = AppVerifierAgent(llm_call=lambda m: GOOD_REPLY, workdir=tmp_path)
    report = agent.build_and_verify(DEMO_REQUEST, DEMO_TEST)
    assert report["status"] == "passed"
    assert report["attempts_used"] == 1
    assert report["final_state"]["remaining"] == 1
    assert len(report["final_state"]["state"]["todos"]) == 2


def test_agent_fixes_broken_spec_then_passes(tmp_path):
    calls = {"n": 0}

    def stub(messages):
        calls["n"] += 1
        return BROKEN_SPEC if calls["n"] == 1 else GOOD_REPLY

    agent = AppVerifierAgent(llm_call=stub, workdir=tmp_path)
    report = agent.build_and_verify(DEMO_REQUEST, DEMO_TEST)
    assert report["status"] == "passed"
    assert report["attempts_used"] == 2
    # the first attempt failed: the list renders state key "tasks", which is empty
    first = report["attempts"][0]["test"]
    assert first["passed"] is False
    assert any("state.todos.length" in f for f in first["failures"])


def test_agent_reports_failure_after_max_attempts(tmp_path):
    agent = AppVerifierAgent(llm_call=lambda m: BROKEN_SPEC,
                             workdir=tmp_path)
    report = agent.build_and_verify(DEMO_REQUEST, DEMO_TEST, max_attempts=2)
    assert report["status"] == "failed"
    assert report["attempts_used"] == 2
    assert len(report["attempts"]) == 2


def test_agent_handles_unparsable_spec(tmp_path):
    calls = {"n": 0}

    def stub(messages):
        calls["n"] += 1
        return "not yaml at all {{{" if calls["n"] == 1 else GOOD_REPLY

    agent = AppVerifierAgent(llm_call=stub, workdir=tmp_path)
    report = agent.build_and_verify(DEMO_REQUEST, DEMO_TEST)
    assert report["status"] == "passed"
    assert report["attempts_used"] == 2
    assert "spec invalid" in report["attempts"][0]["error"]


def test_agent_default_model_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "groq/llama-3.3-70b-versatile")
    agent = AppVerifierAgent(llm_call=lambda m: GOOD_REPLY, workdir=tmp_path)
    assert agent.model == "groq/llama-3.3-70b-versatile"
    agent2 = AppVerifierAgent(model="openai/gpt-4o", llm_call=lambda m: "", workdir=tmp_path)
    assert agent2.model == "openai/gpt-4o"
