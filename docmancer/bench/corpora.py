"""Built-in corpus registry and resolver for `docmancer bench`.

Provides ready-to-use benchmark corpora that are fetched on demand from
public repositories. The fetch is idempotent: once a corpus is cloned and
its `.fetched` marker is written, subsequent resolve calls return the
cached path without any network I/O.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


FETCHED_MARKER = ".fetched"
LICENSE_ACCEPT_MARKER = ".license-accepted"


@dataclass
class BuiltinCorpus:
    """Descriptor for a built-in benchmark corpus fetched from a public repo."""

    name: str
    description: str
    git_url: str
    license_summary: str
    license_url: str
    # Subdirectory inside the cloned repo that is treated as the corpus root.
    # Use "." to use the repo root itself.
    corpus_subdir: str = "."
    # Expected markdown subdirectories inside corpus_subdir (for the Q&A source refs).
    source_subdirs: list[str] = field(default_factory=list)


BUILTIN_CORPORA: dict[str, BuiltinCorpus] = {
    "lenny": BuiltinCorpus(
        name="lenny",
        description="Lenny's Newsletter and Podcast starter pack: 10 newsletters + 50 podcast transcripts on product, growth, and AI.",
        git_url="https://github.com/LennysNewsletter/lennys-newsletterpodcastdata.git",
        license_summary=(
            "Lenny's starter dataset is free for personal, non-commercial use only.\n"
            "You may study it, remix it locally, and publish projects built with it.\n"
            "You may NOT redistribute the raw files or use them commercially."
        ),
        license_url="https://github.com/LennysNewsletter/lennys-newsletterpodcastdata/blob/main/LICENSE.md",
        corpus_subdir=".",
        source_subdirs=["newsletters", "podcasts"],
    ),
}


def corpora_root() -> Path:
    """Root directory under which all built-in corpora are cached."""
    env = os.environ.get("DOCMANCER_BENCH_CORPORA_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".docmancer" / "bench" / "corpora"


def corpus_path(name: str) -> Path:
    """Full path where a named built-in corpus lives on disk."""
    return corpora_root() / name


def is_fetched(name: str) -> bool:
    """True only if the corpus directory exists AND the .fetched marker is present.

    The marker is written atomically *after* a successful clone, so a
    partial or interrupted fetch will not be mistaken for a completed one.
    """
    base = corpus_path(name)
    return base.exists() and (base / FETCHED_MARKER).is_file()


def list_builtin() -> list[BuiltinCorpus]:
    return sorted(BUILTIN_CORPORA.values(), key=lambda c: c.name)


def get_builtin(name: str) -> BuiltinCorpus:
    try:
        return BUILTIN_CORPORA[name]
    except KeyError as exc:
        available = ", ".join(sorted(BUILTIN_CORPORA)) or "(none)"
        raise KeyError(f"Unknown built-in corpus: {name!r}. Available: {available}") from exc


def resolve_corpus(
    name: str,
    *,
    accept_license: bool | None = None,
    refresh: bool = False,
    echo=print,
    confirm=None,
) -> Path:
    """Return the on-disk path to a built-in corpus, fetching if needed.

    Idempotency contract: if the corpus has already been fetched (marker
    file present) and `refresh=False`, this function does NOT touch the
    network, does NOT reprompt for license, and returns immediately.

    Args:
        name: Key from `BUILTIN_CORPORA`.
        accept_license: Pre-accept the license non-interactively. If None,
            `confirm` is called (or True is assumed when confirm is None).
        refresh: If True, delete any cached copy and re-fetch.
        echo: Callable used for user-facing messages (default `print`).
        confirm: Callable `(prompt: str) -> bool` used when interactive
            license confirmation is needed. If None, license is assumed
            accepted when `accept_license` is True or when a prior accept
            marker exists.
    """
    spec = get_builtin(name)
    base = corpus_path(name)
    subdir = base / spec.corpus_subdir if spec.corpus_subdir != "." else base

    if refresh and base.exists():
        shutil.rmtree(base)

    if is_fetched(name):
        return subdir

    prior_accept = (base / LICENSE_ACCEPT_MARKER).is_file() if base.exists() else False
    if not prior_accept:
        if accept_license is False:
            raise RuntimeError(
                f"License for corpus {name!r} not accepted. "
                f"Re-run with acceptance or accept interactively."
            )
        if accept_license is None:
            echo(f"\nBuilt-in corpus: {spec.name}")
            echo(f"  {spec.description}")
            echo(f"  Source: {spec.git_url}")
            echo("")
            echo(spec.license_summary)
            echo(f"  Full license: {spec.license_url}")
            echo("")
            if confirm is not None:
                if not confirm(f"Fetch {spec.name} and accept the license? [y/N] "):
                    raise RuntimeError(f"User declined license for corpus {name!r}.")
            # If no confirm callback, treat as explicit accept (caller opted in).

    _fetch_corpus(spec, base, echo=echo)
    base.mkdir(parents=True, exist_ok=True)
    (base / LICENSE_ACCEPT_MARKER).write_text(
        json.dumps(
            {
                "accepted_at": datetime.now(timezone.utc).isoformat(),
                "license_url": spec.license_url,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_fetched_marker(base, spec)
    return subdir


def _fetch_corpus(spec: BuiltinCorpus, target: Path, *, echo=print) -> None:
    """Clone the public repo into `target`. Falls back to httpx tarball on git failure."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)

    echo(f"Fetching {spec.name} from {spec.git_url} ...")

    git_ok = False
    try:
        result = subprocess.run(
            ["git", "clone", "--depth=1", spec.git_url, str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        git_ok = result.returncode == 0
        if not git_ok:
            echo(f"git clone failed: {result.stderr.strip()[:200]}")
    except FileNotFoundError:
        echo("git not found on PATH; falling back to tarball download.")

    if not git_ok:
        _fetch_tarball_fallback(spec, target, echo=echo)

    echo(f"Fetched {spec.name} to {target}")


def _fetch_tarball_fallback(spec: BuiltinCorpus, target: Path, *, echo=print) -> None:
    """Download the repo as a tarball when `git` is unavailable."""
    import io
    import tarfile

    import httpx

    # Derive GitHub tarball URL from the git URL.
    git_url = spec.git_url
    if not git_url.startswith("https://github.com/"):
        raise RuntimeError(
            f"Cannot fall back to tarball for non-GitHub URL: {git_url}"
        )
    owner_repo = git_url[len("https://github.com/") :].removesuffix(".git")
    tarball_url = f"https://codeload.github.com/{owner_repo}/tar.gz/refs/heads/main"

    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        resp = client.get(tarball_url)
        resp.raise_for_status()
        buf = io.BytesIO(resp.content)

    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=buf, mode="r:gz") as tf:
        members = tf.getmembers()
        if not members:
            raise RuntimeError("Empty tarball from GitHub")
        top = members[0].name.split("/", 1)[0]
        for member in members:
            if not member.name.startswith(top + "/") and member.name != top:
                continue
            rel = member.name[len(top) + 1 :] if member.name != top else ""
            if not rel:
                continue
            dest = target / rel
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                extracted = tf.extractfile(member)
                if extracted is None:
                    continue
                dest.write_bytes(extracted.read())


def _write_fetched_marker(target: Path, spec: BuiltinCorpus) -> None:
    commit = _git_head_sha(target) or ""
    payload = {
        "corpus": spec.name,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "git_url": spec.git_url,
        "commit": commit,
    }
    (target / FETCHED_MARKER).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _git_head_sha(target: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        return None
    return None
