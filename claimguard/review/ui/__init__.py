"""The reviewer interface: one self-contained page over the existing review API.

WHAT THIS PACKAGE IS
--------------------
The interface required behaviour 4 (a review queue with filters, original values
and clear unresolved-check counts) and behaviour 5 (confirm, dismiss with reason,
request information, corrected-for-recheck) of ``docs/01_Challenge_Brief.md``,
delivered as a single HTML page and its assets, served by the SAME FastAPI app as
the review API. There is no build step, no bundler, no CDN and no second server:
``index.html`` loads ``styles.css``, ``app.js`` and ``render.mjs`` from
``/review/static/`` and talks to the endpoints the app already exposes
(``GET /v1/queue``, ``GET /v1/runs/{run_id}/results``,
``GET|POST /v1/runs/{run_id}/decisions``,
``POST /v1/claims/{claim_id}/recheck``). This package adds no API endpoint and
decides nothing: every status it shows came from the deterministic engine, and
every decision it records goes through the API's own validation.

HOW IT IS WIRED IN
------------------
``claimguard.review.app`` gains exactly one line, inside ``create_app``:

    app.include_router(getattr(__import__("claimguard.review.ui", fromlist=["router"]), "router"))

The ``__import__`` is what keeps that a one-line change; :data:`router` below is
the ordinary ``APIRouter`` it needs, and the routes are declared here.

WHAT THE PAGE IS NOT
--------------------
*   It is **not authenticated**. The pack's own review page says "Reviewer
    identity is self-declared", and so is this one: whoever types a name into the
    actor field is recorded as the actor. There is no login, no session, no
    permission model, and nothing here should be exposed to an untrusted network
    without one.
*   It is **not an adjudication surface**. There is no approve, deny, pay or
    submit-to-payer control, because the API has no such operation.
*   It **marks the wording, never the verdict**. Each explanation carries the
    provenance the API serves beside the record
    (``GET /v1/runs/{run_id}/results`` → ``explanations``): deterministic text,
    model-assisted wording, or a fallback where the deterministic text stands
    because the model path did not deliver. The marker says nothing about the
    status above it, which is the engine's and always was.
*   It is **not a rendering surface for HTML**. Claim text (``notes``), attachment
    ``text``, rule ``explanation``/``corrective_action``, explanation-provenance
    values (which can quote a model's malformed output) and API error bodies are
    untrusted data: ``render.mjs`` writes them with ``textContent`` only, never as
    markup (see that file's untrusted-data policy comment).
*   It **cannot show the submitted envelope**, because no endpoint returns it.
    The correction form therefore takes the corrected envelope as pasted JSON;
    that limitation is stated on the page itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse

#: Where the page and its assets live. Served from disk; no build step produces them.
STATIC_DIR: Final[Path] = Path(__file__).resolve().parent / "static"

#: The page and its assets, with the media type each is served as. The explicit
#: map IS the traversal defence: a request either names a key here or it is a 404,
#: so no path arithmetic is ever performed on caller input.
ASSETS: Final[dict[str, str]] = {
    "index.html": "text/html",
    "app.js": "text/javascript",
    "render.mjs": "text/javascript",
    "styles.css": "text/css",
}

#: The page's path, and the path pattern for its assets.
PAGE_PATH: Final = "/review"
ASSET_PATH: Final = "/review/static/{asset}"

router = APIRouter(tags=["reviewer interface"])


def _asset(name: str) -> FileResponse:
    """Serve one known asset, or raise 404 for anything else."""
    media_type = ASSETS.get(name)
    if media_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no such reviewer-interface asset: {name!r}",
        )
    return FileResponse(STATIC_DIR / name, media_type=media_type)


@router.get(PAGE_PATH, response_class=HTMLResponse, summary="Reviewer interface (HTML page)")
def reviewer_page() -> FileResponse:
    """The reviewer interface: queue, claim detail, decisions and recheck."""
    return _asset("index.html")


@router.get(ASSET_PATH, response_class=FileResponse, include_in_schema=False)
def reviewer_asset(asset: str) -> FileResponse:
    """One of the page's assets (stylesheet, modules)."""
    return _asset(asset)
