"""Open Knowledge Format (OKF) support for docmancer.

OKF v0.1 is a vendor-neutral spec from Google Cloud: a directory of markdown
files with YAML frontmatter. docmancer already produces markdown plus
frontmatter across fetch, memory, and consolidation, so OKF is an output and
input adapter over the existing pipeline.
"""

from __future__ import annotations

from .format import (
    OKF_VERSION,
    RESERVED_FIELDS,
    RESERVED_FILENAMES,
    dump_frontmatter,
    is_okf_bundle,
    parse_frontmatter,
)

__all__ = [
    "OKF_VERSION",
    "RESERVED_FIELDS",
    "RESERVED_FILENAMES",
    "dump_frontmatter",
    "is_okf_bundle",
    "parse_frontmatter",
]
