"""Tests for the renderer: HTML output and the PNG screenshot."""

from pathlib import Path

from PIL import Image

from agent_app_verifier.driver import AppDriver
from agent_app_verifier.renderer import compute_layout, render_html, render_png

from conftest import load_spec


def make_driver(tmp_path):
    return AppDriver(load_spec(), workdir=tmp_path)


def test_html_contains_all_components(tmp_path):
    driver = make_driver(tmp_path)
    html = driver.html()
    assert "<title>Todos</title>" in html
    assert "data-testid='new_todo'" in html
    assert "data-testid='add_button'" in html
    assert "Add a todo..." in html
    assert "0 left" in html
    assert "updated 0s ago" in html


def test_html_shows_todos_and_done_state(tmp_path):
    driver = make_driver(tmp_path)
    driver.type("new_todo", "Buy milk")
    driver.tap("add_button")
    driver.type("new_todo", "Walk dog")
    driver.tap("add_button")
    driver.tap("todo_list", index=0, part="toggle")
    html = driver.html()
    assert "Buy milk" in html and "Walk dog" in html
    assert "class='done'" in html
    assert "1 left" in html


def test_html_escapes_text(tmp_path):
    driver = make_driver(tmp_path)
    driver.type("new_todo", "<script>alert(1)</script>")
    driver.tap("add_button")
    html = driver.html()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_dark_theme(tmp_path):
    driver = make_driver(tmp_path)
    driver.prefer("dark")
    html = driver.html()
    assert "rgb(24, 26, 32)" in html  # dark background


def test_png_dimensions_match_layout(tmp_path):
    driver = make_driver(tmp_path)
    driver.type("new_todo", "A")
    driver.tap("add_button")
    out = tmp_path / "shot.png"
    info = render_png(driver.runtime.spec, driver.runtime.state,
                      driver.runtime.inputs, "light", out)
    img = Image.open(out)
    assert img.size == (info["width"], info["height"])
    assert img.mode == "RGB"


def test_png_dark_differs_from_light(tmp_path):
    driver = make_driver(tmp_path)
    light = tmp_path / "light.png"
    dark = tmp_path / "dark.png"
    render_png(driver.runtime.spec, driver.runtime.state, driver.runtime.inputs, "light", light)
    render_png(driver.runtime.spec, driver.runtime.state, driver.runtime.inputs, "dark", dark)
    assert Image.open(light).getpixel((0, 0)) != Image.open(dark).getpixel((0, 0))


def test_png_grows_with_more_todos(tmp_path):
    driver = make_driver(tmp_path)
    out1 = tmp_path / "one.png"
    info1 = render_png(driver.runtime.spec, driver.runtime.state,
                       driver.runtime.inputs, "light", out1)
    driver.type("new_todo", "A")
    driver.tap("add_button")
    driver.type("new_todo", "B")
    driver.tap("add_button")
    out2 = tmp_path / "two.png"
    info2 = render_png(driver.runtime.spec, driver.runtime.state,
                       driver.runtime.inputs, "light", out2)
    assert info2["height"] > info1["height"]


def test_layout_empty_list_has_one_row(tmp_path):
    spec = load_spec()
    boxes = compute_layout(spec, {"todos": []})
    assert boxes["todo_list"].h > 0
    assert "todo_list:0" not in boxes
