"""Scripted test files: tests written as scripts of the 10 operations.

A test file is YAML:

```yaml
name: todo-demo
steps:
  - op: type
    id: new_todo
    text: "Buy milk"
  - op: tap
    id: add_button
  - op: assert
    path: state.todos
    equals: 3
  - op: clock
    advance: 60
  - op: assert
    path: tree.updated_timer.text
    contains: "60s"
```

Steps are driver operations (``tap``, ``type``, ``clock``, ``prefer``,
``screenshot``, ``tree``, ``state``, ``layout``, ``logs``, ``perf``) plus
``assert`` steps. An assert reads a dotted path out of the latest
``state`` / ``tree`` snapshot:

- ``state.todos`` — the todos list (``.length`` suffix counts it)
- ``state.remaining`` — todos not done
- ``state.elapsed`` — virtual seconds since last update
- ``state.clock`` — virtual clock seconds
- ``tree.<id>.text`` — a component's displayed text
- ``tree.<id>.value`` — an input's current value
- ``tree.todo_list.items`` — the list items

Assertions support ``equals``, ``contains`` and ``length``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .driver import AppDriver, DriverError

ASSERT_OPS = ("equals", "contains", "length")


@dataclass
class StepResult:
    step: int
    op: str
    ok: bool
    detail: str = ""
    result: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestReport:
    name: str
    passed: bool
    steps: list[StepResult] = field(default_factory=list)

    @property
    def failures(self) -> list[StepResult]:
        return [s for s in self.steps if not s.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "steps": [
                {"step": s.step, "op": s.op, "ok": s.ok, "detail": s.detail}
                for s in self.steps
            ],
            "failures": [s.detail for s in self.failures],
        }


def _resolve(path: str, driver: AppDriver) -> Any:
    """Resolve a dotted assert path against state/tree snapshots."""
    if path.startswith("state."):
        snapshot = driver.state()
        view: dict[str, Any] = dict(snapshot["state"])
        view["remaining"] = snapshot["remaining"]
        view["elapsed"] = snapshot["elapsed"]
        value: Any = _walk(view, path[len("state."):])
        return value
    if path.startswith("tree."):
        tree = driver.tree()
        rest = path[len("tree."):]
        comp_id, _, attr = rest.partition(".")
        for node in tree["components"]:
            if node["id"] == comp_id:
                if attr == "":
                    return node
                if attr == "items":
                    return node.get("items", [])
                return node.get(attr)
        raise DriverError(f"no component {comp_id!r} in tree")
    raise DriverError(f"assert path must start with 'state.' or 'tree.', got {path!r}")


def _walk(value: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if part == "length":
            return len(value)
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list):
            value = value[int(part)]
        else:
            raise DriverError(f"cannot walk {part!r} into {value!r}")
    return value


def run_scripted_test(driver: AppDriver, test_path: str | Path) -> TestReport:
    """Run a scripted test file against a live driver. Never raises."""
    raw = yaml.safe_load(Path(test_path).read_text(encoding="utf-8"))
    name = raw.get("name", Path(test_path).stem)
    steps = raw.get("steps", [])
    report = TestReport(name=name, passed=True)

    for i, step in enumerate(steps):
        op = step.get("op")
        try:
            if op == "assert":
                value = _resolve(step["path"], driver)
                if "equals" in step:
                    expected = step["equals"]
                    ok = value == expected
                    detail = f"{step['path']} == {expected!r} (got {value!r})"
                elif "contains" in step:
                    ok = str(step["contains"]) in str(value)
                    detail = f"{step['path']} contains {step['contains']!r} (got {value!r})"
                elif "length" in step:
                    ok = len(value) == int(step["length"])
                    detail = f"{step['path']} length == {step['length']} (got {len(value)})"
                else:
                    raise DriverError(f"assert needs one of {ASSERT_OPS}: {step!r}")
                report.steps.append(StepResult(i + 1, "assert", ok, detail))
                if not ok:
                    report.passed = False
                continue
            args = {k: v for k, v in step.items() if k != "op"}
            if "id" in args:  # test files say `id:`; driver methods take component_id
                args["component_id"] = args.pop("id")
            result = driver.call(op, **args)
            report.steps.append(StepResult(
                i + 1, op, True, f"{op} ok", result))
        except Exception as exc:  # a step failure fails the test, not the run
            report.steps.append(StepResult(i + 1, op or "?", False, str(exc)))
            report.passed = False
    return report


def parse_test_file(test_path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(test_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "steps" not in raw:
        raise DriverError(f"test file {test_path} needs a 'steps' list")
    return raw
