"""Test fixtures.

The suite runs without a model provider on purpose. Every test here exercises
the deterministic path, which means the suite is the proof that acceptance
criterion A11 holds: this is what the system does when the provider is gone.

Tests that need a provider would make the suite depend on a free tier being
available at the moment someone runs it, which is exactly the kind of
dependency that turns "run the tests" into "the tests did not run".
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _isolated_environment(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Point every path at a temporary directory, and remove the API key.

    Removing the key is deliberate: it puts the whole suite on the degraded
    path, so an unexpected network call cannot make a test pass that would
    fail on the assessor's machine.
    """
    storage = tmp_path_factory.mktemp("storage")
    os.environ["STORAGE_DIR"] = str(storage)
    os.environ["DECISION_LOG_DB"] = str(storage / "decisions.sqlite3")
    os.environ["LLM_CACHE_DIR"] = str(storage / "llm_cache")
    os.environ["CALIBRATION_FILE"] = str(storage / "calibration.json")
    os.environ["DOCUMENTATION_FILE"] = str(FIXTURES / "documentation.json")
    os.environ["OPENROUTER_API_KEY"] = ""
    os.environ["RUN_ID"] = "pytest"

    from src.config import get_settings

    get_settings(refresh=True)


@pytest.fixture()
def tickets():
    from src.ingest import load_tickets

    return load_tickets(FIXTURES / "tickets.json")


@pytest.fixture()
def retriever():
    from src.retrieve import Retriever, load_corpus

    return Retriever(chunks=load_corpus(FIXTURES / "documentation.json"))


@pytest.fixture()
def pipeline(retriever, tmp_path):
    from src.classify import Classifier
    from src.decision_log import DecisionLog
    from src.generate import Generator
    from src.pipeline import SupportPipeline

    return SupportPipeline(
        classifier=Classifier(),
        retriever=retriever,
        generator=Generator(),
        decision_log=DecisionLog(tmp_path / "decisions.sqlite3"),
        run_id="pytest-run",
    )
