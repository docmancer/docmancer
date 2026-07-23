#!/usr/bin/env python3
"""Download the pinned public benchmark datasets without provider calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "datasets.lock.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def download(target: Path, source: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(source, headers={"User-Agent": "docmancer-public-benchmark/1"})
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    temporary.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--dataset", choices=["locomo", "longmemeval-s", "all"], default="all")
    args = parser.parse_args()
    locked = json.loads(LOCK.read_text(encoding="utf-8"))
    names = list(locked) if args.dataset == "all" else [args.dataset]
    for name in names:
        row = locked[name]
        target = args.data_dir / row["filename"]
        if not target.exists() or digest(target) != row["sha256"]:
            download(target, row["source"])
        actual = digest(target)
        if actual != row["sha256"]:
            target.unlink(missing_ok=True)
            raise SystemExit(f"{name}: checksum mismatch, expected {row['sha256']}, got {actual}")
        print(f"{name}: {target} sha256={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
