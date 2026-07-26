#!/usr/bin/env python3
"""Create checked-in benchmark artifacts without redistributing dataset text."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


# Anything that quotes or paraphrases dataset text. `generated_answer` and
# `judge_reason` come from the answer arm and would otherwise republish the
# reference text the retrieval arm is careful to strip.
PRIVATE_RESULT_FIELDS = {
    "question",
    "answer",
    "generated_answer",
    "judge_reason",
    "reference_answer",
}


def public_row(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in PRIVATE_RESULT_FIELDS
    }


def publish(source: Path, destination: Path) -> dict:
    report = json.loads(source.read_text(encoding="utf-8"))
    rows = [public_row(row) for row in report["results"]]
    report["results"] = rows
    # The answer arm names this field `retrieval_rank`, so keying only on
    # `rank` classified every answer row as a loss.
    report["losses"] = [
        row
        for row in rows
        if not row.get("excluded")
        and not row.get("rank")
        and not row.get("retrieval_rank")
    ]
    report["publication_note"] = (
        "Question and answer text are omitted. Download the pinned official dataset "
        "and join on case ID to reproduce or inspect a case."
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    report = publish(args.source, args.destination)
    print(
        f"Published {report['benchmark']}: {report['cases_evaluated']} evaluated, "
        f"{len(report['losses'])} losses"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
