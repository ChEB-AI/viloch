"""Browser tests of the standalone page (``pytest -m e2e``; needs the e2e extra and
``playwright install chromium``)."""

from __future__ import annotations

import socket
import threading
import time

import pytest

pytestmark = pytest.mark.e2e

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def server_url():
    import uvicorn

    from viloch.web.app import create_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def page(server_url):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(server_url)
        # the initial parse of the example rule; later parses must not race it
        page.wait_for_selector("#block-canvas .atom-box")
        yield page
        browser.close()
        assert not errors, errors


def set_text(page, text: str) -> None:
    page.fill("#asp-text", text)
    page.click("#to-blocks")


def test_text_becomes_blocks(page):
    set_text(
        page, "concept(M) :- has_atom(M,A), has_atom(M,B), n(A), o(B), bDOUBLE(A,B)."
    )
    page.wait_for_function(
        "document.querySelectorAll('#block-canvas .atom-box').length === 2"
    )
    assert page.locator("#block-canvas .chip-label", has_text="Nitrogen").count() == 1


def test_count_box_round_trips(page):
    rule = "concept(M) :- has_atom(M,_), #count{ A : has_atom(M,A), o(A) } >= 2."
    set_text(page, rule)
    page.wait_for_selector("#block-canvas .group-frame")
    page.click("#to-text")
    page.wait_for_function(
        "document.getElementById('asp-text').value.includes('#count{ V1 : has_atom(V0,V1), o(V1) } >= 2')"
    )


def test_raw_clause_is_shown_with_reason(page):
    set_text(page, "concept(M) :- mol_weight(M,W), W > 150.")
    page.wait_for_selector("#block-canvas .raw-clause")
    assert "W > 150" in page.locator(".raw-why").inner_text()


def test_explain_molecule(page):
    set_text(page, "concept(M) :- has_atom(M,A), o(A).")
    page.fill("#smiles", "CCO")
    page.click("#explain-molecule")
    page.wait_for_selector("#explanation img", timeout=60_000)
    assert page.locator(".verdict").inner_text().lower() == "accepted"


def test_block_edit_updates_text(page):
    set_text(page, "concept(M) :- has_atom(M,A), o(A), in_ring(A).")
    page.wait_for_selector("#block-canvas .chip-label:text('In a ring')")
    chip = page.locator("#block-canvas .chip", has_text="In a ring")
    chip.locator(".chip-x").click()
    page.wait_for_function(
        "document.getElementById('asp-text').value.trim() === "
        "'concept(V0) :- has_atom(V0,V1), o(V1).'"
    )
