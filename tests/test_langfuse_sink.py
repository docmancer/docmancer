from unittest.mock import patch, MagicMock
from docmancer.core.config import DocmancerConfig, TelemetryConfig


def test_try_send_skips_when_telemetry_disabled():
    from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
    config = DocmancerConfig(telemetry=TelemetryConfig(enabled=False))
    mock_trace = MagicMock()
    # Should not raise
    try_send_to_langfuse(mock_trace, config)


def test_try_send_skips_when_no_telemetry_config():
    from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
    config = DocmancerConfig()
    mock_trace = MagicMock()
    try_send_to_langfuse(mock_trace, config)


def test_try_send_skips_when_provider_not_langfuse():
    from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
    config = DocmancerConfig(telemetry=TelemetryConfig(enabled=True, provider="other"))
    mock_trace = MagicMock()
    try_send_to_langfuse(mock_trace, config)


def test_try_send_handles_missing_langfuse_package():
    """Should log debug and not crash when langfuse is not installed."""
    from docmancer.telemetry.langfuse_sink import try_send_to_langfuse
    import docmancer.telemetry.langfuse_sink as sink_mod
    sink_mod._WARNED_MISSING_KEYS = False  # Reset state

    config = DocmancerConfig(telemetry=TelemetryConfig(enabled=True, provider="langfuse"))
    mock_trace = MagicMock()
    # This will fail because langfuse is likely not installed — that's fine
    try_send_to_langfuse(mock_trace, config)  # Should not raise
