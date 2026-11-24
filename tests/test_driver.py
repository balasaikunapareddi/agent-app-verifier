"""Tests for the driver: all ten operations, the clock, and error paths."""

import pytest

from agent_app_verifier.driver import AppDriver, DriverError

from conftest import load_spec


def make_driver(tmp_path):
    return AppDriver(load_spec(), workdir=tmp_path)


def add_todo(driver, text):
    driver.type("new_todo", text)
    return driver.tap("add_button")


def test_tree_starts_empty(tmp_path):
    driver = make_driver(tmp_path)
    tree = driver.tree()
    assert tree["ok"] and tree["title"] == "Todos"
    ids = [c["id"] for c in tree["components"]]
    assert ids == ["header", "new_todo", "add_button", "todo_list", "remaining", "updated_timer"]
    assert tree["components"][3]["items"] == []
    assert tree["components"][4]["text"] == "0 left"


def test_type_and_tap_add(tmp_path):
    driver = make_driver(tmp_path)
    driver.type("new_todo", "Buy milk")
    assert driver.state()["inputs"]["new_todo"] == "Buy milk"
    result = driver.tap("add_button")
    assert result["ok"] and result["remaining"] == 1
    state = driver.state()
    assert state["state"]["todos"] == [{"id": "todo-1", "text": "Buy milk", "done": False}]
    assert state["inputs"]["new_todo"] == ""  # clear step ran


def test_toggle_and_delete(tmp_path):
    driver = make_driver(tmp_path)
    add_todo(driver, "A")
    add_todo(driver, "B")
    add_todo(driver, "C")
    driver.tap("todo_list", index=0, part="toggle")
    assert driver.state()["remaining"] == 2
    assert driver.state()["state"]["todos"][0]["done"] is True
    driver.tap("todo_list", index=1, part="delete")
    todos = driver.state()["state"]["todos"]
    assert [t["text"] for t in todos] == ["A", "C"]
    assert driver.state()["remaining"] == 1


def test_tap_toggle_defaults_to_toggle(tmp_path):
    driver = make_driver(tmp_path)
    add_todo(driver, "A")
    driver.tap("todo_list", index=0)
    assert driver.state()["state"]["todos"][0]["done"] is True


def test_tap_unknown_component(tmp_path):
    driver = make_driver(tmp_path)
    with pytest.raises(DriverError, match="no component"):
        driver.tap("nope")


def test_tap_non_tappable(tmp_path):
    driver = make_driver(tmp_path)
    with pytest.raises(DriverError, match="cannot tap"):
        driver.tap("header")


def test_tap_list_out_of_range(tmp_path):
    driver = make_driver(tmp_path)
    with pytest.raises(DriverError, match="out of range"):
        driver.tap("todo_list", index=0, part="toggle")


def test_tap_list_bad_part(tmp_path):
    driver = make_driver(tmp_path)
    add_todo(driver, "A")
    with pytest.raises(DriverError, match="unknown list part"):
        driver.tap("todo_list", index=0, part="explode")


def test_type_into_non_input(tmp_path):
    driver = make_driver(tmp_path)
    with pytest.raises(DriverError, match="cannot type"):
        driver.type("add_button", "x")


def test_state_shape(tmp_path):
    driver = make_driver(tmp_path)
    add_todo(driver, "A")
    snap = driver.state()
    assert snap["remaining"] == 1
    assert snap["elapsed"] == 0
    assert snap["theme"] == "light"
    assert snap["state"]["clock"] == 0


def test_layout_boxes_inside_canvas(tmp_path):
    driver = make_driver(tmp_path)
    add_todo(driver, "A")
    add_todo(driver, "B")
    layout = driver.layout()
    assert layout["ok"]
    for box in layout["boxes"].values():
        assert 0 <= box["x"] and box["x"] + box["width"] <= 480
        assert box["y"] >= 0 and box["height"] > 0
    assert "todo_list:0" in layout["boxes"]
    assert "todo_list:1" in layout["boxes"]
    # list items stack vertically, no overlap
    assert layout["boxes"]["todo_list:0"]["y"] < layout["boxes"]["todo_list:1"]["y"]


def test_logs_record_actions(tmp_path):
    driver = make_driver(tmp_path)
    add_todo(driver, "A")
    logs = driver.logs()
    assert logs["ok"]
    messages = [e["message"] for e in logs["logs"]]
    assert any("action add_todo ran" in m for m in messages)
    assert all("t" in e for e in logs["logs"])


def test_clock_read_and_advance(tmp_path):
    driver = make_driver(tmp_path)
    assert driver.clock()["clock"] == 0
    result = driver.clock(advance=60)
    assert result["clock"] == 60 and result["advanced_by"] == 60
    assert driver.clock()["clock"] == 60


def test_clock_cannot_go_backwards(tmp_path):
    driver = make_driver(tmp_path)
    with pytest.raises(DriverError, match="backwards"):
        driver.clock(advance=-5)


def test_clock_drives_timer(tmp_path):
    driver = make_driver(tmp_path)
    add_todo(driver, "A")  # touch sets last_updated = 0
    driver.clock(advance=60)
    assert driver.state()["elapsed"] == 60
    tree = driver.tree()
    timer = next(c for c in tree["components"] if c["id"] == "updated_timer")
    assert timer["text"] == "updated 60s ago"


def test_prefer_theme(tmp_path):
    driver = make_driver(tmp_path)
    assert driver.prefer()["theme"] == "light"
    assert driver.prefer("dark")["theme"] == "dark"
    assert driver.prefer()["theme"] == "dark"
    assert driver.state()["theme"] == "dark"


def test_prefer_bad_theme(tmp_path):
    driver = make_driver(tmp_path)
    with pytest.raises(DriverError, match="theme"):
        driver.prefer("neon")


def test_perf_records_every_op(tmp_path):
    driver = make_driver(tmp_path)
    driver.tree()
    add_todo(driver, "A")
    driver.clock(advance=5)
    perf = driver.perf()
    assert perf["ok"]
    ops = [row["op"] for row in perf["operations"]]
    assert ops == ["tree", "type", "tap", "clock"]
    assert all(row["ms"] >= 0 for row in perf["operations"])
    assert perf["total_ms"] >= 0
    assert perf["count"] == 4


def test_screenshot_writes_png(tmp_path):
    driver = make_driver(tmp_path)
    add_todo(driver, "Buy milk")
    info = driver.screenshot()
    assert info["ok"] and info["format"] == "PNG"
    assert info["width"] == 480 and info["height"] > 0
    path = tmp_path / f"screenshot-001.png"
    assert path.exists() and path.stat().st_size > 1000


def test_call_dispatch_unknown_op(tmp_path):
    driver = make_driver(tmp_path)
    with pytest.raises(DriverError, match="unknown operation"):
        driver.call("teleport")
