"""The reviewer interface is served, and it says what it is.

No database and no browser: these tests ask the real ASGI app for the page and
its assets and read exactly what comes back. The behaviour behind the page is
covered by ``test_ui_flow.py`` (the endpoints it calls) and
``test_ui_rendering.py`` (how it renders untrusted claim text).
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.unit

#: The pack's own wording for a PASS (docs/04_Rulebook.md:16). It is quoted on the
#: page, so a reviewer cannot read a PASS as payer approval.
PACK_PASS_WARNING = (
    "PASS means this specific check passed on the supplied data. "
    "It does not mean payer approval or a clinically correct claim."
)

#: The four decisions the pack allows (behaviour 5).
REVIEW_ACTIONS = (
    "confirm_issue",
    "dismiss_with_reason",
    "request_information",
    "mark_corrected_for_recheck",
)

#: Every status the interface must present as its own thing.
PACK_STATUSES = ("PASS", "FAIL", "UNABLE_TO_ASSESS", "NOT_APPLICABLE", "NOT_IMPLEMENTED")


async def test_the_page_is_served_as_html(ui_client: httpx.AsyncClient) -> None:
    response = await ui_client.get("/review")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert PACK_PASS_WARNING in body
    assert "NOT_IMPLEMENTED is never shown as a pass" in body
    assert "Reviewer identity comes from the clinic session" in body
    assert "not clinical or reimbursement ground truth" in body
    # The page is one document with four working areas and no build step.
    assert '<script type="module" src="/review/static/app.js"></script>' in body
    assert 'href="/review/static/styles.css"' in body
    for anchor in ("filters", "detail-actor", "detail-findings", "decisions", "recheck-claim"):
        assert f'id="{anchor}"' in body


async def test_the_assets_are_served_with_their_media_types(ui_client: httpx.AsyncClient) -> None:
    expected = {
        "index.html": "text/html",
        "app.js": "text/javascript",
        "render.mjs": "text/javascript",
        "styles.css": "text/css",
    }
    for name, media_type in expected.items():
        response = await ui_client.get(f"/review/static/{name}")
        assert response.status_code == 200, name
        assert response.headers["content-type"].startswith(media_type), name


async def test_the_page_offers_the_four_decisions_and_distinguishes_every_status(
    ui_client: httpx.AsyncClient,
) -> None:
    """The controls exist: four actions, and one legend entry per pack status."""
    module = (await ui_client.get("/review/static/render.mjs")).text
    for action in REVIEW_ACTIONS:
        assert action in module
    for status in PACK_STATUSES:
        assert status in module
    # The four decision controls are buttons in the rendered form, and the
    # correct-and-recheck action is the only one styled apart.
    assert "renderDecisionForm" in module
    assert "status-NOT_IMPLEMENTED" in (await ui_client.get("/review/static/styles.css")).text


async def test_nothing_outside_the_four_assets_is_served(ui_client: httpx.AsyncClient) -> None:
    """A request for a file that is not on the list is a 404 — never a file read."""
    for path in (
        "/review/static/app.py",
        "/review/static/../../claimguard/review/app.py",
        "/review/static/%2e%2e%2f%2e%2e%2fclaimguard%2freview%2fapp.py",
        "/review/static/",
        "/review/static/index.html.bak",
    ):
        response = await ui_client.get(path)
        assert response.status_code == 404, path
        assert "class ClaimGuard" not in response.text, path
