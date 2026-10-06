"""Regressions for the actual Colab dependency conflict and hidden subprocess errors."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[2]


def test_hub_pin_satisfies_transformers_and_tokenizers_constraints() -> None:
    pins = dict(
        line.split("==", 1)
        for line in (ROOT / "notebooks/requirements-slm.txt").read_text().splitlines()
        if "==" in line and not line.startswith("#")
    )
    version = pins["huggingface-hub"]
    assert version in SpecifierSet(">=1.31.0,<3.0")  # Transformers 5.18.0 metadata.
    assert version in SpecifierSet(">=0.16.4,<2.0")  # Tokenizers 0.23.1/0.23.2 metadata.


def test_visible_command_reports_stderr_before_raising(capsys: pytest.CaptureFixture[str]) -> None:
    runtime = importlib.import_module("notebooks.colab_runtime")
    with pytest.raises(subprocess.CalledProcessError) as caught:
        runtime.run_visible(
            [
                sys.executable,
                "-c",
                "import sys; print('dependency conflict', file=sys.stderr); sys.exit(3)",
            ]
        )
    assert caught.value.returncode == 3
    assert "dependency conflict" in capsys.readouterr().out


def test_visible_command_streams_successful_output(capsys: pytest.CaptureFixture[str]) -> None:
    runtime = importlib.import_module("notebooks.colab_runtime")
    runtime.run_visible([sys.executable, "-c", "print('setup complete')"])
    assert "setup complete" in capsys.readouterr().out


def test_visible_python_children_are_unbuffered(capsys: pytest.CaptureFixture[str]) -> None:
    runtime = importlib.import_module("notebooks.colab_runtime")
    runtime.run_visible([sys.executable, "-c", "import sys; print(sys.stdout.write_through)"])
    assert capsys.readouterr().out.strip() == "True"


def test_native_bf16_gate_rejects_emulated_t4_support(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = importlib.import_module("notebooks.slm_benchmark_runner")
    cuda = SimpleNamespace(
        is_available=lambda: True,
        is_bf16_supported=lambda *, including_emulation=True: including_emulation,
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=cuda, bfloat16="bf16"))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace())
    with pytest.raises(RuntimeError, match="Native BF16 unsupported"):
        runner.load_gpu("phi4-mini", "bf16", "unused-revision", 8)


def test_setup_refreshes_existing_checkout_before_importing_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads((ROOT / "notebooks/slm_explanation_benchmark_colab.ipynb").read_text())
    source = "".join(payload["cells"][1]["source"])
    source = source.replace('Path("/content/ClaimGuard")', f"Path({str(ROOT)!r})")
    commands: list[list[str]] = []

    def record(command: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def output(command: Sequence[str], **_kwargs: object) -> str:
        commands.append(list(command))
        return "" if "status" in command else "test-revision"

    runtime = importlib.import_module("notebooks.colab_runtime")
    monkeypatch.setattr(subprocess, "run", record)
    monkeypatch.setattr(subprocess, "check_output", output)
    monkeypatch.setattr(runtime, "run_visible", record)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    exec(compile(source, "colab-setup-test", "exec"), {})  # noqa: S102 - trusted repository cell
    fetch = ["/usr/bin/git", "fetch", "origin", "main"]
    checkout = ["/usr/bin/git", "checkout", "--detach", "FETCH_HEAD"]
    assert fetch in commands and checkout in commands
    assert commands.index(fetch) < commands.index(checkout)
    assert commands.index(checkout) < next(
        i for i, command in enumerate(commands) if "pip" in command
    )
