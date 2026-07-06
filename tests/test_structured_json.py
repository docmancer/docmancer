from docmancer.ai.memory_schemas import ConsolidatedMemoryDraft
from docmancer.ai.structured_json import json_schema


def _object_schemas(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _object_schemas(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _object_schemas(item)


def test_json_schema_is_strict_for_nested_objects():
    schema = json_schema(ConsolidatedMemoryDraft)

    objects = list(_object_schemas(schema))
    assert objects
    for obj in objects:
        assert obj["additionalProperties"] is False
        if "properties" in obj:
            assert obj["required"] == list(obj["properties"])
