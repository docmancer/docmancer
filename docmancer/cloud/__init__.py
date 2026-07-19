"""Zero-knowledge cloud-sync client primitives.

Local recall never depends on this package. Cloud modules move encrypted
record revisions only when the user explicitly enables a workspace.
"""

PROTOCOL_VERSION = "1"

__all__ = ["PROTOCOL_VERSION"]
