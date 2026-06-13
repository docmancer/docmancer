import json

from docmancer.harness.paths import project_path_for_slug_dir


def test_recovers_cwd_from_session_jsonl(tmp_path):
    proj = tmp_path / ".claude" / "projects" / "-Users-x-my-app"
    proj.mkdir(parents=True)
    (proj / "s.jsonl").write_text(json.dumps({"cwd": "/Users/x/my-app"}) + "\n")
    assert project_path_for_slug_dir(proj) == "/Users/x/my-app"


def test_recovers_cwd_when_not_on_first_line(tmp_path):
    # The cwd is not always on line 0 (a summary/meta record can precede it).
    proj = tmp_path / ".claude" / "projects" / "-Users-x-my-app"
    proj.mkdir(parents=True)
    lines = [
        json.dumps({"type": "summary", "summary": "older session"}),
        json.dumps({"type": "meta"}),
        json.dumps({"type": "user", "cwd": "/Users/x/real-app"}),
    ]
    (proj / "s.jsonl").write_text("\n".join(lines) + "\n")
    assert project_path_for_slug_dir(proj) == "/Users/x/real-app"


def test_falls_back_to_slug_when_no_session(tmp_path):
    proj = tmp_path / ".claude" / "projects" / "-Users-x-app"
    proj.mkdir(parents=True)
    # Documented lossy fallback; acceptable because include/exclude also match
    # the raw scope string, and the user can correct via explicit globs.
    assert project_path_for_slug_dir(proj).startswith("/Users/x")
