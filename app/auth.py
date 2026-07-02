"""Shared API-key auth (+db module) — born-secure default for the Standard SOV Program.

A CRUD surface is never unauthenticated where it matters: when APP_API_KEY is set (qual/uat/prod), every
mutating/listing endpoint that Depends(require_api_key) requires a matching X-API-Key. When APP_API_KEY is
unset (local dev / the boot-smoke) the dependency is a no-op so the artifact still boots. Set APP_API_KEY
in every non-dev environment. (Replace with SOV-issued per-program keys / the +secrets module as needed.)"""
from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("APP_API_KEY", "")
    if not expected:
        return  # unset → dev/boot convenience; set APP_API_KEY in qual/uat/prod to ENFORCE
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="valid X-API-Key required")
