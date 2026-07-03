"""Server-side CoEv2 client used by the BFF."""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import httpx

from app.config import Settings, settings

LOG = logging.getLogger(__name__)
REDACTED = "[REDACTED]"


class CoEv2ClientError(Exception):
    def __init__(self, message: str, correlation_id: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.correlation_id = correlation_id
        self.status_code = status_code


def redact(value: Any, secret: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            key: redact(item, secret)
            for key, item in value.items()
            if key.lower() != "authorization"
        }
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, str):
        clean = value
        if secret:
            clean = clean.replace(secret, REDACTED)
        return clean
    return value


class CoEv2Client:
    def __init__(self, config: Settings = settings, timeout: float = 10.0):
        self.config = config
        self.timeout = timeout

    def grade(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        return self._request("POST", "/grade", json=payload)

    def get_job(self, job_id: str) -> tuple[dict[str, Any], str]:
        return self._request("GET", f"/jobs/{job_id}")

    def _request(self, method: str, path: str, **kwargs: Any) -> tuple[dict[str, Any], str]:
        correlation_id = str(uuid4())
        url = f"{self.config.coev2_api_base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = dict(kwargs.pop("headers", {}))
        headers["X-Correlation-ID"] = correlation_id
        if self.config.council_api_key:
            headers["Authorization"] = f"Bearer {self.config.council_api_key}"

        log_headers = redact(headers, self.config.council_api_key)
        if self.config.council_api_key and "Authorization" in headers:
            log_headers["Authorization"] = f"Bearer {REDACTED}"
        LOG.info("forwarding CoEv2 request %s %s headers=%s", method, url, log_headers)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            LOG.warning("CoEv2 timeout correlation_id=%s", correlation_id)
            raise CoEv2ClientError("CoEv2 request timed out", correlation_id, 504) from exc
        except httpx.HTTPError as exc:
            LOG.warning("CoEv2 request failed correlation_id=%s error=%s", correlation_id, exc)
            raise CoEv2ClientError("CoEv2 request failed", correlation_id, 502) from exc

        if response.status_code >= 500:
            LOG.warning(
                "CoEv2 server error correlation_id=%s status=%s",
                correlation_id,
                response.status_code,
            )
            raise CoEv2ClientError("CoEv2 backend error", correlation_id, 502)

        try:
            data: Any = response.json()
        except ValueError:
            data = {"raw": response.text}
        return redact(data, self.config.council_api_key), correlation_id


def get_coev2_client() -> CoEv2Client:
    return CoEv2Client()
