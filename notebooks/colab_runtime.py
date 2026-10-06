"""Surface subprocess output in Colab, whose kernel hides inherited child streams."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence


def run_visible(command: Sequence[str]) -> None:
    """Stream both channels through notebook stdout and preserve failure status."""
    with subprocess.Popen(  # noqa: S603 - caller supplies trusted argv; never uses a shell
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
        returncode = process.wait()
    if returncode:
        raise subprocess.CalledProcessError(returncode, list(command))
