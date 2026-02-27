"""Auth/audit unit tests for dashboard links API helpers."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from dashboard.api import server


def _make_request(
    *,
    token: str | None = None,
    host: str = "127.0.0.1",
    method: str = "POST",
    path: str = "/api/links",
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if token is not None:
        headers.append((b"x-links-token", token.encode("utf-8")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": (host, 12345),
        "server": ("127.0.0.1", 8000),
    }

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, _receive)


def test_require_links_admin_denies_missing_token() -> None:
    request = _make_request(token=None, method="POST")
    with pytest.raises(HTTPException):
        server._require_links_admin(request)


def test_require_links_admin_accepts_admin_token() -> None:
    request = _make_request(token=server._LINKS_ADMIN_TOKEN, method="POST")
    server._require_links_admin(request)


def test_require_links_access_write_accepts_api_token() -> None:
    request = _make_request(token=server._LINKS_API_TOKEN, method="POST")
    server._require_links_access(request, write=True)


def test_audit_links_mutation_writes_event(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    class _StubStore:
        def log_admin_audit_event(self, event: dict[str, Any]) -> None:
            captured.append(event)

    monkeypatch.setattr(server, "_link_store", _StubStore())
    request = _make_request(token=server._LINKS_ADMIN_TOKEN, method="POST", path="/api/links/calibrate/fam")
    request.state.links_actor_fingerprint = "actor_fp"
    server._audit_links_mutation(
        request,
        method="POST",
        path="/api/links/calibrate/fam",
        status_code=200,
        payload_hash="hash_abc",
    )
    assert len(captured) == 1
    assert captured[0]["action"] == "POST /api/links/calibrate/fam"
    assert captured[0]["payload_hash"] == "hash_abc"


@pytest.mark.asyncio
async def test_links_middleware_audits_failed_mutation_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    class _StubStore:
        def log_admin_audit_event(self, event: dict[str, Any]) -> None:
            captured.append(event)

    monkeypatch.setattr(server, "_link_store", _StubStore())
    request = _make_request(
        token=server._LINKS_ADMIN_TOKEN,
        method="POST",
        path="/api/links/calibrate/fam",
    )

    async def _call_next(_request: Request) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "conflict"})

    response = await server._links_api_auth_middleware(request, _call_next)
    assert response.status_code == 409
    assert len(captured) == 1
    assert captured[0]["status_code"] == 409
    assert captured[0]["metadata"]["outcome"] == "failure"


@pytest.mark.asyncio
async def test_links_middleware_audits_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    class _StubStore:
        def log_admin_audit_event(self, event: dict[str, Any]) -> None:
            captured.append(event)

    monkeypatch.setattr(server, "_link_store", _StubStore())
    request = _make_request(token=None, method="POST", path="/api/links/calibrate/fam")

    async def _call_next(_request: Request) -> JSONResponse:
        return JSONResponse(status_code=200, content={"ok": True})

    response = await server._links_api_auth_middleware(request, _call_next)
    assert response.status_code in {401, 403}
    assert len(captured) == 1
    assert int(captured[0]["status_code"]) in {401, 403}
    assert captured[0]["metadata"]["outcome"] == "failure"
