"""Declarative UI spec format (mini-Contract) for agent-app-verifier.

A spec is a small, typed YAML document describing one screen of an app:
which components it has, what state it holds, and what happens when the
agent (or a user) taps a button. The driver interprets the spec; the
renderer turns it into HTML and a PNG screenshot.

Example (the built-in todo app, specs/todo.yaml)::

    app:
      title: "Todos"
      theme: light
    components:
      - id: header
        type: text
        text: "My Todos"
      - id: new_todo
        type: input
        placeholder: "Add a todo..."
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

Action steps
------------
- ``append: {list, item}``   append a templated item to a state list
- ``remove: {list, index}``  remove the item at ``index`` (``{index}`` = tap target)
- ``toggle: {list, index}``  flip the ``done`` flag of the item at ``index``
- ``set: {key, value}``      set a state key to a templated value
- ``clear: <input id>``      empty an input's current value
- ``touch: true``            set ``last_updated`` to the virtual clock
- ``log: <message>``         append a templated message to the app log

Templates substitute ``{input:<id>}`` (current input value), ``{index}``
(tap target index), ``{clock}`` (virtual seconds) and any state key
(``{remaining}``, ``{elapsed}``, ``{count}``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

COMPONENT_TYPES = ("text", "input", "button", "list", "timer")
STEP_KEYS = ("append", "remove", "toggle", "set", "clear", "touch", "log")
_TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")


class SpecError(ValueError):
    """Raised when a spec document is malformed or invalid."""


@dataclass
class Component:
    id: str
    type: str
    text: str = ""
    template: str = ""
    placeholder: str = ""
    label: str = ""
    action: str = ""
    submit_action: str = ""
    source: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Component":
        if not isinstance(raw, dict):
            raise SpecError(f"component must be a mapping, got {raw!r}")
        comp_id = raw.get("id")
        if not comp_id or not isinstance(comp_id, str):
            raise SpecError(f"component needs a string id, got {raw!r}")
        comp_type = raw.get("type")
        if comp_type not in COMPONENT_TYPES:
            raise SpecError(
                f"component {comp_id!r} has unknown type {comp_type!r}; "
                f"expected one of {COMPONENT_TYPES}"
            )
        if comp_type == "button" and not raw.get("action"):
            raise SpecError(f"button {comp_id!r} needs an 'action'")
        if comp_type == "list" and not raw.get("source"):
            raise SpecError(f"list {comp_id!r} needs a 'source' state key")
        known = {
            "id", "type", "text", "template", "placeholder", "label",
            "action", "submit_action", "source",
        }
        unknown = set(raw) - known
        if unknown:
            raise SpecError(f"component {comp_id!r} has unknown keys: {sorted(unknown)}")
        return cls(
            id=comp_id,
            type=comp_type,
            text=str(raw.get("text", "")),
            template=str(raw.get("template", "")),
            placeholder=str(raw.get("placeholder", "")),
            label=str(raw.get("label", "")),
            action=str(raw.get("action", "")),
            submit_action=str(raw.get("submit_action", "")),
            source=str(raw.get("source", "")),
        )


@dataclass
class AppSpec:
    title: str = "App"
    theme: str = "light"
    components: list[Component] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    actions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def component(self, comp_id: str) -> Component:
        for comp in self.components:
            if comp.id == comp_id:
                return comp
        raise SpecError(f"no component with id {comp_id!r}")

    def component_ids(self) -> list[str]:
        return [c.id for c in self.components]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppSpec":
        if not isinstance(raw, dict):
            raise SpecError("spec must be a mapping")
        app = raw.get("app", {}) or {}
        if not isinstance(app, dict):
            raise SpecError("'app' section must be a mapping")
        title = str(app.get("title", "App"))
        theme = str(app.get("theme", "light"))
        if theme not in ("light", "dark"):
            raise SpecError(f"theme must be 'light' or 'dark', got {theme!r}")

        raw_components = raw.get("components", [])
        if not isinstance(raw_components, list) or not raw_components:
            raise SpecError("'components' must be a non-empty list")
        components = [Component.from_dict(c) for c in raw_components]
        ids = [c.id for c in components]
        if len(set(ids)) != len(ids):
            raise SpecError(f"duplicate component ids: {ids}")

        state = raw.get("state", {}) or {}
        if not isinstance(state, dict):
            raise SpecError("'state' must be a mapping")
        state = dict(state)
        state.setdefault("clock", 0)
        state.setdefault("last_updated", 0)
        if "todos" not in state:
            state["todos"] = []

        raw_actions = raw.get("actions", {}) or {}
        if not isinstance(raw_actions, dict):
            raise SpecError("'actions' must be a mapping")
        actions: dict[str, list[dict[str, Any]]] = {}
        for name, steps in raw_actions.items():
            if not isinstance(steps, list):
                raise SpecError(f"action {name!r} must be a list of steps")
            validated: list[dict[str, Any]] = []
            for step in steps:
                if not isinstance(step, dict) or len(step) != 1:
                    raise SpecError(f"action {name!r} step must be a single-key mapping: {step!r}")
                key = next(iter(step))
                if key not in STEP_KEYS:
                    raise SpecError(f"action {name!r} has unknown step {key!r}; expected one of {STEP_KEYS}")
                validated.append(step)
            actions[name] = validated

        # Every button/input action must exist.
        for comp in components:
            for action_name in (comp.action, comp.submit_action):
                if action_name and action_name not in actions:
                    raise SpecError(
                        f"component {comp.id!r} references unknown action {action_name!r}"
                    )
        return cls(title=title, theme=theme, components=components,
                   state=state, actions=actions)

    @classmethod
    def from_yaml(cls, text: str) -> "AppSpec":
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecError(f"invalid YAML: {exc}") from exc
        if raw is None:
            raise SpecError("empty spec document")
        return cls.from_dict(raw)

    @classmethod
    def from_file(cls, path: str | Path) -> "AppSpec":
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": {"title": self.title, "theme": self.theme},
            "components": [
                {k: v for k, v in {
                    "id": c.id, "type": c.type, "text": c.text,
                    "template": c.template, "placeholder": c.placeholder,
                    "label": c.label, "action": c.action,
                    "submit_action": c.submit_action, "source": c.source,
                }.items() if v}
                for c in self.components
            ],
            "state": self.state,
            "actions": self.actions,
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)


def render_template(template: str, context: dict[str, Any]) -> str:
    """Substitute ``{name}`` placeholders from ``context`` (missing -> '')."""
    def repl(match: re.Match[str]) -> str:
        return str(context.get(match.group(1), ""))
    return _TEMPLATE_RE.sub(repl, template)


def render_value(value: Any, context: dict[str, Any]) -> Any:
    """Recursively render templates inside a step's value (str/dict/list)."""
    if isinstance(value, str):
        return render_template(value, context)
    if isinstance(value, dict):
        return {k: render_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, context) for v in value]
    return value
