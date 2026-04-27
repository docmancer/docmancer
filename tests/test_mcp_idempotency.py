from docmancer.mcp import idempotency


def _db(tmp_path):
    return tmp_path / "idem.db"


def test_explicit_key_wins(tmp_path):
    args = {"limit": 3, idempotency.EXPLICIT_KEY_ARG: "user-key"}
    key, reused = idempotency.get_or_create_key("tool", args, db_path=_db(tmp_path))
    assert key == "user-key"
    assert reused is True


def test_fingerprint_cache_reuses(tmp_path):
    db = _db(tmp_path)
    key1, reused1 = idempotency.get_or_create_key("t", {"a": 1}, db_path=db, now=1000)
    key2, reused2 = idempotency.get_or_create_key("t", {"a": 1}, db_path=db, now=1500)
    assert key1 == key2
    assert reused1 is False
    assert reused2 is True


def test_different_args_get_different_keys(tmp_path):
    db = _db(tmp_path)
    k1, _ = idempotency.get_or_create_key("t", {"a": 1}, db_path=db, now=1000)
    k2, _ = idempotency.get_or_create_key("t", {"a": 2}, db_path=db, now=1000)
    assert k1 != k2


def test_explicit_key_excluded_from_fingerprint(tmp_path):
    db = _db(tmp_path)
    k1, _ = idempotency.get_or_create_key("t", {"a": 1}, db_path=db, now=1000)
    args = {"a": 1, idempotency.EXPLICIT_KEY_ARG: "x"}
    k2, reused = idempotency.get_or_create_key("t", args, db_path=db, now=1500)
    assert k2 == "x"
    assert reused is True
    # fingerprint cache for {"a": 1} should still find k1 if explicit not passed
    k3, reused3 = idempotency.get_or_create_key("t", {"a": 1}, db_path=db, now=2000)
    assert k3 == k1
    assert reused3 is True


def test_ttl_expiry(tmp_path):
    db = _db(tmp_path)
    k1, _ = idempotency.get_or_create_key("t", {"a": 1}, db_path=db, ttl_seconds=10, now=1000)
    k2, reused = idempotency.get_or_create_key("t", {"a": 1}, db_path=db, ttl_seconds=10, now=2000)
    assert k1 != k2
    assert reused is False
