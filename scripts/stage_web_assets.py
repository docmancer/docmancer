"""Stage the statically exported localhost UI into the Python package."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from docmancer.web.api import LOCAL_API_VERSION


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "web" / "out"
DEFAULT_DESTINATION = ROOT / "docmancer" / "web" / "static"
BRAND_ASSET = ROOT / "readme-assets" / "wizard-logo.png"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage(source: Path, destination: Path) -> dict[str, object]:
    source = source.resolve()
    destination = destination.resolve()
    if not (source / "index.html").is_file():
        raise SystemExit(f"static export is missing {source / 'index.html'}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docmancer-web-", dir=destination.parent) as temp:
        staged = Path(temp) / "static"
        shutil.copytree(source, staged)
        shutil.copy2(BRAND_ASSET, staged / "wizard-logo.png")
        files = sorted(path for path in staged.rglob("*") if path.is_file())
        manifest: dict[str, object] = {
            "format": 1,
            "local_api_version": LOCAL_API_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "files": {
                path.relative_to(staged).as_posix(): sha256(path)
                for path in files
            },
        }
        (staged / "asset-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        previous = destination.with_name(f".{destination.name}.previous")
        if previous.exists():
            shutil.rmtree(previous)
        if destination.exists():
            destination.rename(previous)
        staged.rename(destination)
        if previous.exists():
            shutil.rmtree(previous)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    manifest = stage(args.source, args.destination)
    print(f"staged {len(manifest['files'])} web assets into {args.destination}")


if __name__ == "__main__":
    main()
