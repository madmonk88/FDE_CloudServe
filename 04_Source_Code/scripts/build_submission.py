"""Build the submission archive, in exactly the mandated shape.

    python 04_Source_Code/scripts/build_submission.py

The submission guide is specific and several of its requirements are the kind
that get missed at eleven o'clock on the last night: the archive name, exactly
four top-level folders with prescribed names, nothing nested inside another
folder, and the per-file naming convention.

This builds that archive from the repository and then prints the guide's own
final checklist, marking each item against what is actually present rather
than against what was intended. Items it cannot verify mechanically — whether
the audio is audible, whether the video runs to length — are printed as
manual checks rather than silently passed.

`00_Provided_Pack/` is excluded. It is committed to the repository so the work
is reproducible from one clone, but the guide says the archive contains
exactly four top-level folders and that is what this produces.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

STUDENT_NAME = "BalakumaranSV"

MANDATED_FOLDERS = ["01_Video", "02_Report", "03_Workbooks", "04_Source_Code"]

# Paths inside 04_Source_Code that must never enter the archive: local state,
# caches, secrets, and anything large enough to be a nuisance.
EXCLUDE_PARTS = {
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv",
    "storage", ".DS_Store", "node_modules", ".mypy_cache", ".ruff_cache",
}
EXCLUDE_NAMES = {".env"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".sqlite3", ".sqlite3-wal", ".sqlite3-shm"}


def should_include(path: Path) -> bool:
    if any(part in EXCLUDE_PARTS for part in path.parts):
        return False
    if path.name in EXCLUDE_NAMES:
        return False
    if path.suffix in EXCLUDE_SUFFIXES:
        return False
    return True


def build(root: Path, out_dir: Path) -> Path:
    archive = out_dir / f"{STUDENT_NAME}_Capstone_Submission.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)

    missing = [f for f in MANDATED_FOLDERS if not (root / f).is_dir()]
    if missing:
        print(f"ERROR: missing mandated folder(s): {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)

    written = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for folder in MANDATED_FOLDERS:
            for path in sorted((root / folder).rglob("*")):
                if not path.is_file() or not should_include(path):
                    continue
                # Relative to the repository root, so the four folders sit at
                # the top of the archive with nothing wrapped around them.
                z.write(path, path.relative_to(root).as_posix())
                written += 1

    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"\n{archive.name}  —  {written} files, {size_mb:.1f} MB")
    print(f"written to {archive}\n")
    return archive


def check(root: Path, archive: Path) -> None:
    """The guide's final checklist, marked against reality."""
    video = root / "01_Video"
    report = root / "02_Report"
    workbooks = root / "03_Workbooks"
    source = root / "04_Source_Code"

    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
    top_level = sorted({n.split("/")[0] for n in names})

    mp4 = list(video.glob("*.mp4"))
    report_pdf = list(report.glob(f"{STUDENT_NAME}_Capstone_Report.pdf"))
    any_pdf = list(report.glob("*.pdf"))
    workbook_docs = [p for p in workbooks.glob("*.doc*")]
    effort_log = list(workbooks.glob("*Effort_Log*"))

    auto: list[tuple[bool, str, str]] = [
        (
            archive.name == f"{STUDENT_NAME}_Capstone_Submission.zip" and " " not in archive.name,
            "Archive named correctly, no spaces",
            archive.name,
        ),
        (
            top_level == MANDATED_FOLDERS,
            "Exactly four top-level folders with the prescribed names",
            ", ".join(top_level) or "none",
        ),
        (
            bool(mp4) or bool(list(video.glob("*.txt"))),
            "Video present (or a text file with the link)",
            mp4[0].name if mp4 else "script only — NOT YET RECORDED",
        ),
        (
            bool(mp4) and mp4[0].name == f"{STUDENT_NAME}_Capstone_Video.mp4" if mp4 else False,
            "Video named FirstnameLastname_Capstone_Video.mp4",
            mp4[0].name if mp4 else "no video",
        ),
        (
            bool(report_pdf),
            "Report present as a single PDF with the mandated name",
            report_pdf[0].name if report_pdf else (
                f"{len(any_pdf)} PDF(s), none named correctly" if any_pdf else "NO PDF"
            ),
        ),
        (
            len(workbook_docs) >= 5,
            "All five stage workbooks included",
            f"{len(workbook_docs)} found",
        ),
        (
            bool(effort_log),
            "Effort log included",
            effort_log[0].name if effort_log else "MISSING",
        ),
        (
            (source / "README.md").exists(),
            "Repository README present",
            "README.md",
        ),
        (
            (source / "requirements.txt").exists() and (source / ".env.example").exists(),
            "requirements.txt and .env.example present",
            "both",
        ),
        (
            all((source / d).is_dir() for d in ("src", "prompts", "tests", "evaluation", "docs", "data")),
            "Mandated repository subfolders present",
            "src, prompts, tests, evaluation, docs, data",
        ),
        (
            (source / ".github" / "workflows").is_dir(),
            "CI configuration present",
            ".github/workflows/",
        ),
        (
            not any(n.endswith("/.env") or n.endswith(".env") for n in names),
            "No .env in the archive",
            "checked",
        ),
    ]

    print("Checklist — mechanically verified")
    print("-" * 68)
    failed = 0
    for ok, label, detail in auto:
        mark = " ok " if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{mark}]  {label}\n           {detail}")

    print()
    print("Checklist — you must confirm these yourself")
    print("-" * 68)
    for item in [
        "The video runs between eighteen and twenty-two minutes.",
        "The audio is clearly audible and the screen content is legible at normal playback.",
        "The live demonstration shows a success, an escalation, a guardrail firing,",
        "  and the unattended run over the full evaluation set.",
        "Every figure and table in the report is numbered, captioned and referred to in the text.",
        "The effort log has entries throughout, not written from memory at the end.",
        "The requirements revision log shows at least one substantive change.",
        "The hidden evaluation set was used once, and the report says when.",
        "The report contains your declaration of AI tool use.",
        "You have cloned this repository into a fresh directory and followed your own",
        "  README from the first line, on a machine that is not the one you built on.",
    ]:
        print(f"  [    ]  {item}")

    print()
    if failed:
        print(f"{failed} mechanical check(s) failed. The archive was still written,")
        print("so you can inspect it, but do not submit it in this state.\n")
    else:
        print("Every mechanical check passed. Work through the manual list above.\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the submission archive.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent,
        help="Repository root (the folder containing 01_Video ... 04_Source_Code).",
    )
    parser.add_argument("--out", type=Path, default=None, help="Where to write the archive.")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    out_dir = (args.out or root.parent).resolve()

    print(f"\nBuilding submission from {root}")
    archive = build(root, out_dir)
    check(root, archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
