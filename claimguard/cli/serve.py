"""``claimguard serve`` — the reviewer API, served by uvicorn.

The target is the factory :func:`claimguard.review.app.create_app`, written once as
:data:`APP_TARGET` and reused by the image, the compose stack and this command, so the
operator path and the container path cannot drift apart. That one application serves the
review API under ``/v1``, the reviewer interface at ``/review``, the OpenAPI docs at
``/docs`` and readiness at ``/v1/health``; this command only starts it.

``--reload`` needs the target as an import string, which it is, and watches the current
directory: run it from the repository root.
"""

from __future__ import annotations

import argparse
from typing import Final, cast

import uvicorn

from claimguard.config import get_settings

#: The ASGI target, as uvicorn's own ``--factory`` form. One definition, three callers.
APP_TARGET: Final = "claimguard.review.app:create_app"

#: Local development binds to loopback; the container passes ``--host 0.0.0.0`` explicitly.
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8000


def run(args: argparse.Namespace) -> int:
    """Start uvicorn in this process; the exit code is uvicorn's own."""
    host = cast(str, args.host)
    port = cast(int, args.port)
    reload = cast(bool, args.reload)
    # Imported here, not at module scope: a problem in the interface package must not be able
    # to take down `status`, `evaluate` or `report`, which do not serve anything.
    from claimguard.review.ui import PAGE_PATH

    base = f"http://{host}:{port}"
    print(f"claimguard serve: {APP_TARGET} on {base}")
    print(f"  reviewer interface  {base}{PAGE_PATH}")
    print(f"  OpenAPI docs        {base}/docs")
    print(f"  readiness           {base}/v1/health")
    if reload:
        print("claimguard serve: reload is on and watches the current directory")
    uvicorn.run(
        APP_TARGET,
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_level=get_settings().log_level.lower(),
    )
    return 0
