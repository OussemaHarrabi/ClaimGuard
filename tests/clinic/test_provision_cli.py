"""First-admin CLI prompts for a secret and prints no credential."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from claimguard.clinic.directory import DIRECTORY_METADATA
from claimguard.clinic.provision import main
from sqlalchemy import Engine, create_engine


@pytest.fixture
def directory_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS claimguard")
        DIRECTORY_METADATA.create_all(connection)
    yield engine
    engine.dispose()


def test_bootstrap_cli_does_not_echo_the_password(
    directory_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["--tenant-id", "clinic-a", "--clinic-name", "Clinic A", "--email", "admin@example.test"],
        engine=directory_engine,
        password_reader=lambda prompt: "correct horse battery staple",
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "clinic-a" in output
    assert "correct horse battery staple" not in output
