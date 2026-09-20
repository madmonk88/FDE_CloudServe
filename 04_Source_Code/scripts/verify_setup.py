"""Check the environment before relying on it.

    python -m scripts.verify_setup

Step two of the assessment procedure is "your README is opened and its
instructions are followed literally". Roughly half of all submissions fail
there, because the README assumed something that existed only on the author's
machine. This script is the answer to that: it checks each assumption and says
which one is wrong, rather than leaving someone to discover it forty tickets
into a run.

It exits zero when the system is ready to run, and non-zero when something
would fail. Nothing here is fatal in itself — the system runs degraded without
a model provider — so warnings and errors are distinguished.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK = "  ok   "
WARN = " warn  "
FAIL = " FAIL  "

errors: list[str] = []
warnings: list[str] = []


def report(status: str, message: str, detail: str = "") -> None:
    print(f"[{status}] {message}")
    if detail:
        for line in detail.splitlines():
            print(f"         {line}")
    if status == FAIL:
        errors.append(message)
    elif status == WARN:
        warnings.append(message)


def main() -> int:
    print("\nCloudServe Support Intelligence — setup check")
    print("=" * 60)

    # -- Python ------------------------------------------------------------
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 10):
        report(OK, f"Python {major}.{minor} (3.10 or later required)")
    else:
        report(FAIL, f"Python {major}.{minor} is too old", "Python 3.10 or later is required.")

    venv = sys.prefix != sys.base_prefix
    if venv:
        report(OK, f"virtual environment active ({sys.prefix})")
    else:
        report(
            WARN,
            "no virtual environment detected",
            "Not fatal, but the most common setup problem is a venv that is not\n"
            "active in the terminal being used. Check with: which python",
        )

    # -- Packages ----------------------------------------------------------
    print("-" * 60)
    required = {
        "httpx": "model provider access",
        "pydantic": "the API request models",
        "fastapi": "the HTTP interface",
        "pytest": "the test suite",
    }
    optional = {
        "sentence_transformers": "dense retrieval (falls back to lexical-only)",
        "chromadb": "vector store (an in-process index is used otherwise)",
        "dotenv": "reading .env (environment variables work without it)",
    }

    for name, purpose in required.items():
        try:
            importlib.import_module(name)
            report(OK, f"{name} — {purpose}")
        except ImportError:
            report(FAIL, f"{name} is not installed", "Run: pip install -r requirements.txt")

    for name, purpose in optional.items():
        try:
            importlib.import_module(name)
            report(OK, f"{name} — {purpose}")
        except ImportError:
            report(WARN, f"{name} is not installed", f"Affects: {purpose}")

    # -- Configuration -----------------------------------------------------
    print("-" * 60)
    from src.config import get_settings

    settings = get_settings(refresh=True)

    if Path(".env").exists():
        report(OK, ".env found")
    else:
        report(
            WARN,
            ".env not found",
            "Copy it: cp .env.example .env — then set OPENROUTER_API_KEY.",
        )

    if settings.model.api_key:
        report(OK, f"model provider key set ({settings.model.provider}, {settings.model.model})")
    else:
        report(
            WARN,
            "no model provider key set",
            "The system will run on its deterministic path: it classifies, retrieves,\n"
            "routes and logs, and escalates every ticket rather than answering.\n"
            "That is a valid run, but automation rate will be zero.",
        )

    # -- Data --------------------------------------------------------------
    print("-" * 60)
    data_dir = settings.paths.data_dir

    doc_file = settings.paths.documentation_file
    if doc_file.exists():
        try:
            from src.retrieve import load_corpus

            chunks = load_corpus(doc_file)
            docs = len({c.doc_id for c in chunks})
            report(OK, f"documentation corpus: {docs} articles, {len(chunks)} chunks")
        except Exception as exc:
            report(FAIL, f"documentation corpus could not be loaded: {exc}")
    else:
        report(
            FAIL,
            f"documentation corpus not found at {doc_file}",
            "Copy documentation.json from the project pack's 05_Datasets folder\n"
            "into the data/ directory. Retrieval cannot run without it.",
        )

    for name, needed_for in [
        ("development_tickets.json", "taxonomy, calibration and threshold tuning"),
        ("validation_tickets.json", "your own evaluation runs"),
        ("ground_truth_responses.json", "response quality comparison"),
    ]:
        path = data_dir / name
        if path.exists():
            try:
                from src.ingest import load_tickets

                n = len(load_tickets(path))
                report(OK, f"{name}: {n} records")
            except Exception as exc:
                report(WARN, f"{name} could not be parsed: {exc}")
        else:
            report(WARN, f"{name} not found", f"Needed for: {needed_for}")

    # -- Fitted artefacts --------------------------------------------------
    print("-" * 60)
    taxonomy_file = settings.paths.storage_dir / "taxonomy.json"
    if taxonomy_file.exists():
        from src.taxonomy import load_taxonomy

        report(OK, f"intent taxonomy: {len(load_taxonomy())} categories, derived from the data")
    else:
        report(
            WARN,
            "no taxonomy file; using the built-in fallback categories",
            "Run: python -m scripts.build_taxonomy --input data/development_tickets.json\n"
            "Without this, predicted categories may not match the evaluation labels.",
        )

    from src import calibration as calib

    calibrator = calib.load()
    if calibrator:
        status = "meets the condition" if calibrator.ece_after <= 0.05 else "does NOT meet it"
        report(
            OK,
            f"confidence calibration fitted on {calibrator.n_samples} samples",
            f"expected calibration error {calibrator.ece_before:.4f} -> "
            f"{calibrator.ece_after:.4f} ({status})",
        )
    else:
        report(
            WARN,
            "no calibration file; confidences are shrunk conservatively",
            "Run: python -m scripts.fit_calibration --input data/development_tickets.json\n"
            "The governance condition asks for stated confidence within 5 points of\n"
            "observed accuracy. Uncalibrated model confidence will not meet it.",
        )

    # -- Live check --------------------------------------------------------
    print("-" * 60)
    if settings.model.api_key:
        from src.llm.provider import LLMClient, ProviderRefused, ProviderUnavailable

        client = LLMClient()
        try:
            reply = client.complete(
                [{"role": "user", "content": "Reply with the single word: ready"}],
                max_tokens=10,
            )
            report(OK, f"model provider answered: {reply.strip()[:40]!r}")
        except ProviderRefused as exc:
            detail = str(exc)
            if "model" in detail.lower() and (
                "not exist" in detail.lower()
                or "not_found" in detail.lower()
                or "unavailable" in detail.lower()
            ):
                detail += (
                    "\n\nThe model id is wrong or your key cannot reach it. Model "
                    "catalogues\nchange without notice and provider documentation lags "
                    "behind them, so do\nnot pick a replacement from a web page. Ask "
                    "your own key instead:\n\n    python -m scripts.list_models --probe "
                    "--set-env\n\nThat prints exactly what this key can run and the .env "
                    "lines to use."
                )
            report(FAIL, "the provider rejected the request", detail)
        except ProviderUnavailable as exc:
            report(WARN, "the provider could not be reached", str(exc))
        finally:
            client.close()

    # -- Summary -----------------------------------------------------------
    print("=" * 60)
    if errors:
        print(f"\n{len(errors)} problem(s) must be fixed before a run:\n")
        for e in errors:
            print(f"  - {e}")
        print()
        return 1

    if warnings:
        print(f"\nReady to run, with {len(warnings)} warning(s):\n")
        for w in warnings:
            print(f"  - {w}")
        print(
            "\nThe system will run. Warnings above describe reduced capability,\n"
            "and every one of them is reported in the run's metrics."
        )
    else:
        print("\nEverything checks out. Ready to run.")

    print(
        "\nNext:\n"
        "  python -m evaluation.harness --input data/validation_tickets.json "
        "--output evaluation/results/\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
