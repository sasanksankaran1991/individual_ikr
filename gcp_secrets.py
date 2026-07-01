"""
Google Secret Manager helpers for individual_ikr.

Secret IDs use the ``ikr-`` prefix by default (separate GCP project from txn-cat).

  ikr-telegram-bot-token
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

DEFAULT_SECRET_PREFIX = "ikr-"

DEFAULT_SECRET_IDS: dict[str, str] = {
    "telegram_bot_token": "telegram-bot-token",
}


def gcp_project() -> str:
    return (
        os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or os.environ.get("GCP_PROJECT", "").strip()
    )


def secret_manager_enabled() -> bool:
    if os.environ.get("USE_SECRET_MANAGER", "").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False
    return bool(gcp_project())


def secret_prefix() -> str:
    if "GCP_SECRET_PREFIX" in os.environ:
        return os.environ.get("GCP_SECRET_PREFIX", "").strip()
    return DEFAULT_SECRET_PREFIX


def secret_id_for(key: str) -> str:
    env_key = f"GCP_SECRET_{key.upper()}"
    override = os.environ.get(env_key, "").strip()
    if override:
        return override
    default = DEFAULT_SECRET_IDS.get(key)
    if not default:
        raise KeyError(f"Unknown secret key: {key!r}")
    return f"{secret_prefix()}{default}"


@lru_cache(maxsize=1)
def _secret_manager_client():
    from google.cloud import secretmanager  # type: ignore[import-untyped]

    return secretmanager.SecretManagerServiceClient()


def _access_secret_raw(secret_id: str) -> str | None:
    if not secret_manager_enabled():
        return None
    project = gcp_project()
    name = f"projects/{project}/secrets/{secret_id}/versions/latest"
    try:
        client = _secret_manager_client()
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
    except Exception as exc:
        print(
            f"Secret Manager: could not read {secret_id!r} ({exc}). "
            "Falling back to file/env.",
            file=sys.stderr,
        )
        return None


def get_secret_text(key: str) -> str | None:
    raw = _access_secret_raw(secret_id_for(key))
    if raw is None:
        return None
    text = raw.strip()
    return text or None


def put_secret_text(key: str, value: str) -> bool:
    if not secret_manager_enabled():
        return False
    project = gcp_project()
    sid = secret_id_for(key)
    parent = f"projects/{project}/secrets/{sid}"
    try:
        client = _secret_manager_client()
        client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": value.encode("utf-8")},
            }
        )
        _access_secret_raw.cache_clear()
        print(f"Secret Manager: updated {sid!r}", file=sys.stderr)
        return True
    except Exception as exc:
        print(f"Secret Manager: could not write {sid!r} ({exc}).", file=sys.stderr)
        return False


def read_first_line_from_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return s
    return ""


def resolve_plaintext(
    *,
    key: str,
    env_var: str,
    file_path: Path,
) -> str:
    env_val = os.environ.get(env_var, "").strip()
    if env_val:
        return env_val
    gsm = get_secret_text(key)
    if gsm:
        return gsm
    return read_first_line_from_file(file_path)
