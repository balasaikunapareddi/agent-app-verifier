"""Tests for the spec format: parsing, validation, templates."""

import pytest

from agent_app_verifier.spec import AppSpec, SpecError, render_template, render_value

from conftest import SPEC_PATH

GOOD = """
app:
  title: "Todos"
  theme: light
components:
  - id: new_todo
    type: input
    placeholder: "Add..."
  - id: add_button
    type: button
    label: "Add"
    action: add_todo
  - id: todo_list
    type: list
    source: todos
  - id: remaining
    type: text
    template: "{remaining} left"
  - id: updated_timer
    type: timer
    template: "updated {elapsed}s ago"
state:
  todos: []
  clock: 0
  last_updated: 0
actions:
  add_todo:
    - append: {list: todos, item: {text: "{input:new_todo}", done: false}}
    - clear: new_todo
    - touch: true
  toggle_todo:
    - toggle: {list: todos, index: "{index}"}
  delete_todo:
    - remove: {list: todos, index: "{index}"}
"""


def test_parse_builtin_spec():
    spec = AppSpec.from_file(SPEC_PATH)
    assert spec.title == "Todos"
    assert spec.theme == "light"
    assert spec.component_ids() == [
        "header", "new_todo", "add_button", "todo_list", "remaining", "updated_timer",
    ]


def test_parse_good_yaml():
    spec = AppSpec.from_yaml(GOOD)
    assert spec.component("add_button").action == "add_todo"
    assert spec.component("todo_list").source == "todos"
    assert "add_todo" in spec.actions
    assert len(spec.actions["add_todo"]) == 3


def test_defaults_fill_clock_and_todos():
    spec = AppSpec.from_yaml(GOOD.replace("  clock: 0\n  last_updated: 0\n", ""))
    assert spec.state["clock"] == 0
    assert spec.state["last_updated"] == 0
    assert spec.state["todos"] == []


def test_unknown_component_type_rejected():
    bad = GOOD.replace('type: input', 'type: widget', 1)
    with pytest.raises(SpecError, match="unknown type"):
        AppSpec.from_yaml(bad)


def test_button_without_action_rejected():
    bad = GOOD.replace('    action: add_todo\n', '')
    with pytest.raises(SpecError, match="needs an 'action'"):
        AppSpec.from_yaml(bad)


def test_list_without_source_rejected():
    bad = GOOD.replace('    source: todos\n', '')
    with pytest.raises(SpecError, match="needs a 'source'"):
        AppSpec.from_yaml(bad)


def test_unknown_action_reference_rejected():
    bad = GOOD.replace('action: add_todo', 'action: explode_todo')
    with pytest.raises(SpecError, match="unknown action"):
        AppSpec.from_yaml(bad)


def test_unknown_step_key_rejected():
    bad = GOOD.replace('- touch: true', '- teleport: true')
    with pytest.raises(SpecError, match="unknown step"):
        AppSpec.from_yaml(bad)


def test_duplicate_component_ids_rejected():
    bad = GOOD + "  - id: new_todo\n    type: text\n    text: dup\n"
    # append inside components list is fiddly; build it directly instead
    spec = AppSpec.from_yaml(GOOD)
    raw = spec.to_dict()
    raw["components"].append({"id": "new_todo", "type": "text", "text": "dup"})
    with pytest.raises(SpecError, match="duplicate"):
        AppSpec.from_dict(raw)


def test_empty_document_rejected():
    with pytest.raises(SpecError):
        AppSpec.from_yaml("")


def test_invalid_yaml_rejected():
    with pytest.raises(SpecError, match="invalid YAML"):
        AppSpec.from_yaml("app: [unclosed")


def test_bad_theme_rejected():
    bad = GOOD.replace('theme: light', 'theme: neon')
    with pytest.raises(SpecError, match="theme"):
        AppSpec.from_yaml(bad)


def test_component_lookup_missing():
    spec = AppSpec.from_yaml(GOOD)
    with pytest.raises(SpecError, match="no component"):
        spec.component("nope")


def test_render_template_substitutes():
    assert render_template("{remaining} left", {"remaining": 2}) == "2 left"
    assert render_template("updated {elapsed}s ago", {"elapsed": 60}) == "updated 60s ago"
    assert render_template("{missing} here", {}) == " here"


def test_render_value_recursive():
    out = render_value({"text": "{input:new_todo}", "done": False, "n": [1, "{clock}"]},
                       {"input:new_todo": "milk", "clock": 5})
    assert out == {"text": "milk", "done": False, "n": [1, "5"]}


def test_round_trip_yaml():
    spec = AppSpec.from_file(SPEC_PATH)
    spec2 = AppSpec.from_yaml(spec.to_yaml())
    assert spec2.component_ids() == spec.component_ids()
    assert spec2.actions == spec.actions
