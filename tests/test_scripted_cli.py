"""Tests for scripted test files and the CLI (offline, no LLM)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_app_verifier.driver import AppDriver
from agent_app_verifier.scripted import parse_test_file, run_scripted_test

from conftest import load_spec

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEMO_TEST = PROJECT_DIR / "examples" / "todo-demo.yaml"


def test_demo_test_passes(tmp_path):
    driver = AppDriver(load_spec(), workdir=tmp_path)
    report = run_scripted_test(driver, DEMO_TEST)
    assert report.passed, report.to_dict()
    assert len(report.steps) == 18
    assert report.failures == []


def test_failing_assert_is_reported_not_raised(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: bad\nsteps:\n"
        "  - op: assert\n    path: state.remaining\n    equals: 99\n",
        encoding="utf-8")
    driver = AppDriver(load_spec(), workdir=tmp_path)
    report = run_scripted_test(driver, bad)
    assert not report.passed
    assert len(report.failures) == 1
    assert "99" in report.failures[0].detail


def test_unknown_op_step_fails_test(tmp_path):
    bad = tmp_path / "bad2.yaml"
    bad.write_text("name: bad2\nsteps:\n  - op: teleport\n", encoding="utf-8")
    driver = AppDriver(load_spec(), workdir=tmp_path)
    report = run_scripted_test(driver, bad)
    assert not report.passed


def test_assert_contains_and_length(tmp_path):
    test = tmp_path / "t.yaml"
    test.write_text(
        "name: t\nsteps:\n"
        "  - op: type\n    id: new_todo\n    text: 'Buy milk'\n"
        "  - op: tap\n    id: add_button\n"
        "  - op: assert\n    path: tree.todo_list.items\n    length: 1\n"
        "  - op: assert\n    path: tree.remaining.text\n    contains: '1 left'\n",
        encoding="utf-8")
    driver = AppDriver(load_spec(), workdir=tmp_path)
    report = run_scripted_test(driver, test)
    assert report.passed, report.to_dict()


def test_assert_bad_path_fails(tmp_path):
    test = tmp_path / "t2.yaml"
    test.write_text(
        "name: t2\nsteps:\n  - op: assert\n    path: nowhere.x\n    equals: 1\n",
        encoding="utf-8")
    driver = AppDriver(load_spec(), workdir=tmp_path)
    report = run_scripted_test(driver, test)
    assert not report.passed


def test_parse_test_file_requires_steps(tmp_path):
    bad = tmp_path / "nope.yaml"
    bad.write_text("name: nope\n", encoding="utf-8")
    with pytest.raises(Exception, match="steps"):
        parse_test_file(bad)


def _run_cli(*args, cwd=PROJECT_DIR):
    env = dict(**{k: v for k, v in __import__("os").environ.items()
                  if "API_KEY" not in k})
    return subprocess.run(
        [sys.executable, "-m", "agent_app_verifier", *args],
        cwd=cwd, capture_output=True, text=True, env=env, timeout=120)


def test_cli_verify_passes(tmp_path):
    result = _run_cli("verify")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["passed"] is True


def test_cli_demo_offline_passes(tmp_path):
    result = _run_cli("demo")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout[result.stdout.index("{"):])
    assert report["status"] == "passed"
    assert report["mode"] == "offline-builtin-spec"


def test_cli_screenshot(tmp_path):
    out = tmp_path / "shot.png"
    result = _run_cli("screenshot", "--out", str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    assert out.exists() and out.stat().st_size > 1000
