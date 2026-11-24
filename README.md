# agent-app-verifier — let the agent see its own app

**The pain:** coding agents write UI code blind. They ship a screen, hope it
renders, and a human has to open the app on every platform and check it by
hand. A todo list that adds items but never updates the "2 left" count ships
anyway, because nothing in the loop ever *looked* at it.

**The fix:** this repo is an agent-native verification loop in the spirit of
[Expo's Exact](https://github.com/expo/exact) (MIT, pre-1.0). Instead of
hoping, the agent builds the app from a small declarative spec, then drives
it itself through ten operations — `tree`, `screenshot`, `tap`, `type`,
`state`, `layout`, `logs`, `clock`, `prefer`, `perf` — seeing the UI as a
rendered image, tapping buttons, typing into fields, jumping the virtual
clock forward 60 seconds to check a timer, and running a scripted test
written in those same ten operations. If the test fails, the agent reads the
failure, fixes the spec, and re-verifies until it passes.

## Quickstart

```bash
git clone <this-repo> && cd agent-app-verifier
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# One command: the agent builds the todo app and verifies it
.venv/bin/python -m agent_app_verifier demo

# Run the scripted test without any LLM (offline)
.venv/bin/python -m agent_app_verifier verify

# Serve the built app locally and click through it
.venv/bin/python -m agent_app_verifier serve   # http://127.0.0.1:8765/

# Render a PNG screenshot of the app
.venv/bin/python -m agent_app_verifier screenshot --out shot.png
```

`demo` uses the live LLM when an API key is configured (`GEMINI_API_KEY`
for the default `gemini/gemini-3.5-flash-lite`, or set `LLM_MODEL` to any
LiteLLM model). With no key it runs offline against the built-in spec, and
the report says which mode ran.

## The loop

```
plain-language request
      │
      ▼
  LLM writes a YAML spec  ──►  spec validated (typed, no guesswork)
      │                              │
      ▼                              ▼
  driver loads the spec ──►  scripted test runs (same 10 ops)
      │                              │
      ├─ pass ──► done, structured report
      └─ fail ──► failure JSON back to the LLM ──► fixed spec, retry (max 3)
```

The agent never writes code for the app itself — it writes a *spec*, and
deterministic code does the rest. That keeps a failure report honest: the
model fixes what the test names, instead of arguing with a vibe.

## The ten operations

| Op | What it does | Returns |
| --- | --- | --- |
| `tree` | UI tree: every component, type, label, current value | JSON tree |
| `screenshot` | Renders the UI as a PNG the agent can see | path, width, height |
| `tap` | Tap a button, a list item's checkbox, or its delete button | action ran, remaining count |
| `type` | Type text into an input | the input's new value |
| `state` | Full app state | todos, inputs, clock, remaining, elapsed |
| `layout` | Bounding box of every component | `{id: {x, y, width, height}}` |
| `logs` | The app's action log | entries with virtual timestamps |
| `clock` | Read, or advance, the virtual clock | current time, elapsed since update |
| `prefer` | Read or set the theme (`light` / `dark`) | current theme |
| `perf` | Timings of every operation run so far | per-op ms, total |

The virtual clock is the point: the agent jumps 60 seconds forward and
reads the "updated 60s ago" timer instantly, instead of waiting a minute.

## The spec format (mini-Contract YAML)

```yaml
app:
  title: "Todos"
  theme: light
components:
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
  toggle_todo:
    - toggle: {list: todos, index: "{index}"}
    - touch: true
  delete_todo:
    - remove: {list: todos, index: "{index}"}
    - touch: true
```

Component types: `text`, `input`, `button`, `list`, `timer`. Action steps:
`append`, `remove`, `toggle`, `set`, `clear`, `touch`, `log`. Templates
substitute `{input:<id>}`, `{index}`, `{clock}`, `{remaining}`, `{count}`,
`{elapsed}`. See `specs/todo.yaml` and `src/agent_app_verifier/spec.py`.

## The scripted test

`examples/todo-demo.yaml` — the same ten operations, run unchanged:

1. Type and add 3 todos → assert 3 todos, 3 left.
2. Toggle the first → assert 2 left.
3. Delete the second → assert 2 todos, 1 left.
4. Advance the virtual clock 60s → assert elapsed is 60 and the timer
   reads "updated 60s ago".
5. `screenshot` + `perf` close the run.

## Why a hand-rolled LiteLLM loop, not a framework

The driver loop *is* the product. A framework (LangGraph, ADK, …) would
add a graph around a loop that is already five lines: ask for a spec,
validate it, run the test, feed the failures back. Keeping it as one
visible `AppVerifierAgent` class with a LiteLLM call means the model can be
swapped by setting `LLM_MODEL` — Gemini today, Groq or OpenRouter tomorrow —
with zero code changes, and the whole loop stays readable in one file.

## Honest limits

- **One platform (web) in this demo.** Exact targets macOS/iOS hosts; this
  repo has a single local web app. The ten operations are platform-shaped
  on purpose, so a second platform would reuse the same test files.
- **The screenshot is a rendered PNG of the UI tree**, drawn with PIL — not
  a capture from a real browser. The agent sees the layout, text and state
  faithfully; it does not see real browser rendering quirks.
- **Pre-1.0 idea, not a port of Exact.** The ten operations and the
  "tests are scripts of the same operations" idea are inspired by Exact's
  README; no Exact code is used here.
- The demo app is a todo list. The loop is the thing being demonstrated,
  not the app.

## Layout

```
src/agent_app_verifier/
  agent.py      AppVerifierAgent — the visible agent class + LiteLLM loop
  prompts.py    system prompt (separate file, never inlined)
  driver.py     AppDriver — the ten operations + virtual clock
  spec.py       typed spec format (YAML in, validated AppSpec out)
  renderer.py   HTML page + PIL screenshot, one shared layout pass
  scripted.py   scripted test files (steps of the ten ops + asserts)
  cli.py        demo / verify / serve / screenshot
specs/todo.yaml           built-in todo spec
examples/todo-demo.yaml   scripted demo test
scripts/live_test.py      live run against a real model
tests/                    offline suite (stub model, no network)
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -q        # offline suite (60 tests)
.venv/bin/python scripts/live_test.py        # via the Gemini key harness, see below
```

Live run (from the repo root):

```bash
python3 ~/workspace/custom-connectors/custom.gemini/bin/run_live.py \
  .venv/bin/python scripts/live_test.py
```
