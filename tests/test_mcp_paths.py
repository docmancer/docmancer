import pytest

from docmancer.mcp import paths


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMANCER_HOME", str(tmp_path))
    paths.ensure_dirs()


@pytest.mark.parametrize(
    "package, version",
    [
        ("..", "1.0"),
        ("stripe", ".."),
        ("../etc", "1.0"),
        ("stripe", "../../etc/passwd"),
        ("foo/../bar", "1.0"),
        ("stripe", "1.0/../../../etc"),
        ("stripe\\evil", "1.0"),
        ("stripe", "1.0\x00bad"),
        ("/abs", "1.0"),
        ("", "1.0"),
        ("stripe", " 1.0 "),
    ],
)
def test_package_dir_rejects_traversal_components(package, version):
    with pytest.raises(ValueError):
        paths.package_dir(package, version)


def test_package_dir_accepts_npm_scoped_name():
    p = paths.package_dir("@scope/pkg", "1.2.3")
    assert p.is_relative_to(paths.servers_dir().resolve())
    assert p.name == "pkg@1.2.3"


def test_package_dir_accepts_plain_spec():
    p = paths.package_dir("stripe", "2026-02-25.clover")
    assert p == paths.servers_dir().resolve() / "stripe@2026-02-25.clover"


def test_secrets_env_file_rejects_traversal():
    with pytest.raises(ValueError):
        paths.secrets_env_file("../etc/passwd")
