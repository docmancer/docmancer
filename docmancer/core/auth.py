from __future__ import annotations

import json
import os
from pathlib import Path

from docmancer.core.registry_errors import AuthRequired
from docmancer.core.registry_models import AuthToken


def load_auth_token(auth_path: str | Path) -> AuthToken | None:
    env_token = os.environ.get("DOCMANCER_REGISTRY_TOKEN")
    if env_token:
        return AuthToken(token=env_token)

    path = Path(auth_path).expanduser()
    if not path.exists():
        return None
    try:
        return AuthToken.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save_auth_token(auth_path: str | Path, auth: AuthToken) -> None:
    path = Path(auth_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(auth.model_dump_json(indent=2), encoding="utf-8")
    path.chmod(0o600)


def remove_auth_token(auth_path: str | Path) -> bool:
    path = Path(auth_path).expanduser()
    if not path.exists():
        return False
    path.unlink()
    return True


def require_auth(auth_path: str | Path) -> AuthToken:
    auth = load_auth_token(auth_path)
    if auth is None:
        raise AuthRequired()
    return auth
