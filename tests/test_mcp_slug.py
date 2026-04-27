from docmancer.mcp.slug import split_tool_name, tool_name, version_slug


def test_version_slug_replaces_dots_dashes_slashes():
    assert version_slug("2026-02-25.clover") == "2026_02_25_clover"
    assert version_slug("0.115.0") == "0_115_0"
    assert version_slug("v18") == "v18"
    assert version_slug("latest") == "latest"


def test_tool_name_uses_double_underscore_between_fields():
    name = tool_name("stripe", "2026-02-25.clover", "payment_intents_create")
    assert name == "stripe__2026_02_25_clover__payment_intents_create"


def test_split_tool_name_roundtrip():
    name = tool_name("fastapi", "0.115.0", "app_add_route")
    parts = split_tool_name(name)
    assert parts == ("fastapi", "0_115_0", "app_add_route")


def test_split_tool_name_rejects_malformed():
    assert split_tool_name("only_one") is None
    assert split_tool_name("a__b__c__d") is None
