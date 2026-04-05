from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_WARNED_MISSING_KEYS = False


class LangfuseSink:
    """Sends QueryTrace spans to Langfuse for observability."""

    def __init__(self, endpoint: str = ""):
        try:
            from langfuse import Langfuse
        except ImportError:
            raise ImportError(
                "The 'langfuse' package is required for telemetry. "
                "Install it with: pip install 'docmancer[langfuse]'"
            )

        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

        if not public_key or not secret_key:
            raise ValueError(
                "Langfuse telemetry enabled but keys not configured. "
                "Run 'docmancer setup' to configure, or set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY."
            )

        kwargs = {"public_key": public_key, "secret_key": secret_key}
        if endpoint:
            kwargs["host"] = endpoint
        self._client = Langfuse(**kwargs)

    def send_trace(self, trace) -> None:
        """Send a QueryTrace to Langfuse."""
        langfuse_trace = self._client.trace(
            name="docmancer-query",
            metadata={"query_text": trace.query_text},
        )

        for span in trace.spans:
            langfuse_trace.span(
                name=span.name,
                start_time=span.start_time,
                end_time=span.end_time,
                metadata=span.metadata if hasattr(span, "metadata") else {},
            )

        self._client.flush()


def try_send_to_langfuse(trace, config) -> None:
    """Attempt to send a trace to Langfuse. Fails silently on any error.

    Args:
        trace: A QueryTrace object
        config: DocmancerConfig with telemetry settings
    """
    global _WARNED_MISSING_KEYS

    if config.telemetry is None or not config.telemetry.enabled:
        return
    if config.telemetry.provider.lower() != "langfuse":
        return

    try:
        sink = LangfuseSink(endpoint=config.telemetry.endpoint)
        sink.send_trace(trace)
    except ImportError:
        logger.debug("Langfuse package not installed, skipping telemetry")
    except ValueError as e:
        if not _WARNED_MISSING_KEYS:
            logger.warning(str(e))
            _WARNED_MISSING_KEYS = True
    except Exception:
        logger.debug("Failed to send trace to Langfuse", exc_info=True)
