"""Driver: Exact's 10 operations against a running app.

The driver owns the app runtime (spec + live state + virtual clock) and
exposes ten operations, each returning structured JSON the agent can read:

    tree        UI tree: every component, its type, label and current value
    screenshot  render the UI as a PNG the agent can "see"
    tap         tap a button / list-item checkbox / delete button
    type        type text into an input
    state       full app state (todos, clock, inputs, remaining, elapsed)
    layout      bounding box of every component
    logs        the app's action log (virtual timestamps)
    clock       read or advance the virtual clock (no real waiting)
    prefer      read or set the theme (light / dark)
    perf        timings of every operation run so far

The virtual clock is the point: an agent can jump an animation or timer
forward 60 seconds and read the result instantly, instead of waiting.
"""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any

from .renderer import compute_layout, display_text, render_html, render_png
from .spec import AppSpec, SpecError, render_value

# The demo contract: the built-in scripted test drives these ids.
REQUIRED_COMPONENT_IDS = ("new_todo", "add_button", "todo_list", "remaining", "updated_timer")


class DriverError(ValueError):
    """Raised when an operation cannot be performed (bad id, bad args)."""


class AppRuntime:
    """Holds a spec and its live state; executes actions; owns the clock."""

    def __init__(self, spec: AppSpec, theme: str | None = None):
        self.spec = spec
        self.theme = theme or spec.theme
        self.state: dict[str, Any] = copy.deepcopy(spec.state)
        self.state.setdefault("clock", 0)
        self.state.setdefault("last_updated", 0)
        self.state.setdefault("todos", [])
        self.inputs: dict[str, str] = {
            c.id: "" for c in spec.components if c.type == "input"
        }
        self.logs: list[dict[str, Any]] = []
        self._next_todo_id = 1
        self._log("app started")

    # -- derived state -------------------------------------------------
    @property
    def remaining(self) -> int:
        return sum(1 for t in self.state["todos"] if not t.get("done"))

    @property
    def elapsed(self) -> int:
        return int(self.state["clock"]) - int(self.state["last_updated"])

    def _log(self, message: str) -> None:
        self.logs.append({"t": int(self.state["clock"]), "message": message})

    def _context(self, index: int | None = None) -> dict[str, Any]:
        ctx: dict[str, Any] = dict(self.state)
        ctx["remaining"] = self.remaining
        ctx["count"] = len(self.state["todos"])
        ctx["elapsed"] = self.elapsed
        ctx["clock"] = int(self.state["clock"])
        ctx.update({f"input:{k}": v for k, v in self.inputs.items()})
        if index is not None:
            ctx["index"] = index
        return ctx

    # -- actions -------------------------------------------------------
    def run_action(self, name: str, index: int | None = None) -> dict[str, Any]:
        steps = self.spec.actions.get(name)
        if steps is None:
            raise DriverError(f"unknown action {name!r}")
        ctx = self._context(index)
        ran: list[str] = []
        for step in steps:
            key = next(iter(step))
            raw = step[key]
            if key == "append":
                item = render_value(raw["item"], ctx)
                if isinstance(item, dict) and "text" in item:
                    item = dict(item)
                    item.setdefault("id", f"todo-{self._next_todo_id}")
                    self._next_todo_id += 1
                self.state[raw["list"]].append(item)
                ran.append(f"appended to {raw['list']}")
            elif key == "remove":
                idx = int(render_value(raw["index"], ctx))
                removed = self.state[raw["list"]].pop(idx)
                ran.append(f"removed {removed.get('text', removed)!r} from {raw['list']}")
            elif key == "toggle":
                idx = int(render_value(raw["index"], ctx))
                item = self.state[raw["list"]][idx]
                item["done"] = not item.get("done", False)
                ran.append(f"toggled {item.get('text', '')!r} done={item['done']}")
            elif key == "set":
                self.state[raw["key"]] = render_value(raw["value"], ctx)
                ran.append(f"set {raw['key']}")
            elif key == "clear":
                self.inputs[raw] = ""
                ran.append(f"cleared input {raw}")
            elif key == "touch":
                self.state["last_updated"] = int(self.state["clock"])
                ran.append("touched last_updated")
            elif key == "log":
                self._log(render_value(raw, ctx))
                ran.append("logged")
        self._log(f"action {name} ran ({'; '.join(ran)})")
        return {"action": name, "steps": ran}

    # -- clock ---------------------------------------------------------
    def advance_clock(self, seconds: int) -> dict[str, Any]:
        if seconds < 0:
            raise DriverError("clock cannot go backwards")
        self.state["clock"] = int(self.state["clock"]) + seconds
        self._log(f"clock advanced +{seconds}s to {self.state['clock']}s")
        return {"clock": int(self.state["clock"]), "advanced_by": seconds,
                "elapsed_since_update": self.elapsed}


class AppDriver:
    """The ten operations. Every call is timed for the ``perf`` op."""

    def __init__(self, spec: AppSpec, workdir: str | Path = "."):
        self.runtime = AppRuntime(spec)
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._timings: list[dict[str, Any]] = []
        self._shot_count = 0

    # -- internal ------------------------------------------------------
    def _timed(self, op: str, fn, *args, **kwargs) -> Any:
        started = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            ok = True
        except Exception as exc:  # recorded, then re-raised
            ok = False
            raise
        finally:
            self._timings.append({
                "op": op, "ms": round((time.perf_counter() - started) * 1000, 2),
                "ok": ok,
            })
        return result

    def _require_component(self, comp_id: str):
        try:
            return self.runtime.spec.component(comp_id)
        except SpecError as exc:
            raise DriverError(str(exc)) from exc

    # -- the ten operations --------------------------------------------
    def tree(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rt = self.runtime
            nodes = []
            for comp in rt.spec.components:
                node: dict[str, Any] = {"id": comp.id, "type": comp.type}
                if comp.type == "text":
                    node["text"] = display_text(rt.spec, comp.id, rt.state, rt.inputs)
                elif comp.type == "timer":
                    node["text"] = display_text(rt.spec, comp.id, rt.state, rt.inputs)
                elif comp.type == "input":
                    node["placeholder"] = comp.placeholder
                    node["value"] = rt.inputs.get(comp.id, "")
                elif comp.type == "button":
                    node["label"] = comp.label
                    node["action"] = comp.action
                elif comp.type == "list":
                    node["items"] = [
                        {"index": i, "id": t.get("id"), "text": t.get("text"),
                         "done": bool(t.get("done"))}
                        for i, t in enumerate(rt.state.get(comp.source, []))
                    ]
                nodes.append(node)
            return {"op": "tree", "ok": True, "title": rt.spec.title,
                    "theme": rt.theme, "components": nodes}
        return self._timed("tree", run)

    def screenshot(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rt = self.runtime
            self._shot_count += 1
            out = self.workdir / f"screenshot-{self._shot_count:03d}.png"
            info = render_png(rt.spec, rt.state, rt.inputs, rt.theme, out)
            return {"op": "screenshot", "ok": True, **info}
        return self._timed("screenshot", run)

    def tap(self, component_id: str, index: int | None = None,
            part: str | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rt = self.runtime
            comp = self._require_component(component_id)
            if comp.type == "button":
                result = rt.run_action(comp.action)
                return {"op": "tap", "ok": True, "id": component_id, **result,
                        "remaining": rt.remaining}
            if comp.type == "list":
                if index is None:
                    raise DriverError(f"tap on list {component_id!r} needs an index")
                items = rt.state.get(comp.source, [])
                if not (0 <= index < len(items)):
                    raise DriverError(
                        f"list {component_id!r} has {len(items)} items; index {index} out of range")
                if part == "delete":
                    result = rt.run_action("delete_todo", index=index)
                elif part in (None, "toggle"):
                    result = rt.run_action("toggle_todo", index=index)
                else:
                    raise DriverError(f"unknown list part {part!r}; use 'toggle' or 'delete'")
                return {"op": "tap", "ok": True, "id": component_id,
                        "index": index, "part": part or "toggle", **result,
                        "remaining": rt.remaining}
            raise DriverError(f"cannot tap a {comp.type} component ({component_id!r})")
        return self._timed("tap", run)

    def type(self, component_id: str, text: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            comp = self._require_component(component_id)
            if comp.type != "input":
                raise DriverError(f"cannot type into a {comp.type} component ({component_id!r})")
            self.runtime.inputs[component_id] = text
            self.runtime._log(f"typed into {component_id}: {text!r}")
            return {"op": "type", "ok": True, "id": component_id, "value": text}
        return self._timed("type", run)

    def state(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rt = self.runtime
            return {"op": "state", "ok": True,
                    "state": copy.deepcopy(rt.state),
                    "inputs": dict(rt.inputs),
                    "remaining": rt.remaining, "elapsed": rt.elapsed,
                    "theme": rt.theme}
        return self._timed("state", run)

    def layout(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rt = self.runtime
            boxes = compute_layout(rt.spec, rt.state)
            return {"op": "layout", "ok": True,
                    "boxes": {k: b.to_dict() for k, b in boxes.items()}}
        return self._timed("layout", run)

    def logs(self) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            return {"op": "logs", "ok": True,
                    "logs": copy.deepcopy(self.runtime.logs)}
        return self._timed("logs", run)

    def clock(self, advance: int | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rt = self.runtime
            if advance is None:
                return {"op": "clock", "ok": True, "clock": int(rt.state["clock"]),
                        "elapsed_since_update": rt.elapsed}
            result = rt.advance_clock(int(advance))
            return {"op": "clock", "ok": True, **result}
        return self._timed("clock", run)

    def prefer(self, theme: str | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            if theme is None:
                return {"op": "prefer", "ok": True, "theme": self.runtime.theme}
            if theme not in ("light", "dark"):
                raise DriverError(f"theme must be 'light' or 'dark', got {theme!r}")
            self.runtime.theme = theme
            self.runtime._log(f"theme set to {theme}")
            return {"op": "prefer", "ok": True, "theme": theme}
        return self._timed("prefer", run)

    def perf(self) -> dict[str, Any]:
        # perf must not time itself (it would always be the slowest row).
        total = sum(t["ms"] for t in self._timings)
        return {"op": "perf", "ok": True, "operations": list(self._timings),
                "total_ms": round(total, 2), "count": len(self._timings)}

    # -- convenience ---------------------------------------------------
    def html(self) -> str:
        rt = self.runtime
        return render_html(rt.spec, rt.state, rt.inputs, rt.theme)

    def call(self, op: str, **kwargs: Any) -> dict[str, Any]:
        """Dispatch one operation by name (used by the scripted runner)."""
        ops = {
            "tree": self.tree, "screenshot": self.screenshot, "tap": self.tap,
            "type": self.type, "state": self.state, "layout": self.layout,
            "logs": self.logs, "clock": self.clock, "prefer": self.prefer,
            "perf": self.perf,
        }
        fn = ops.get(op)
        if fn is None:
            raise DriverError(f"unknown operation {op!r}")
        return fn(**kwargs)
