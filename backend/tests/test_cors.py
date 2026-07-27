"""
Tests for CORS origin restrictions.

Validates that the CORS middleware only allows known local origins
and respects the VOICEBOX_CORS_ORIGINS environment variable.

Builds the app via the real ``backend.app.create_app`` factory so the
tests exercise the actual CORS configuration rather than a copy of it.
"""

import pytest
from starlette.testclient import TestClient

from backend.app import create_app


def _build_client(monkeypatch, env_origins: str | None = None) -> TestClient:
    if env_origins is None:
        monkeypatch.delenv("VOICEBOX_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("VOICEBOX_CORS_ORIGINS", env_origins)
    # Plain TestClient (no context manager) skips lifespan startup, so no
    # model scans or queue workers run — only middleware is exercised.
    return TestClient(create_app())


@pytest.fixture
def client(monkeypatch):
    return _build_client(monkeypatch)


@pytest.fixture
def client_with_custom_origins(monkeypatch):
    return _build_client(monkeypatch, "https://custom.example.com,https://other.example.com")


def _get_with_origin(client: TestClient, origin: str) -> dict:
    """Send a GET with Origin header, return response headers."""
    response = client.get("/health", headers={"Origin": origin})
    return dict(response.headers)


def _preflight(client: TestClient, origin: str) -> dict:
    """Send CORS preflight OPTIONS request, return response headers."""
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    return dict(response.headers)


class TestCORSDefaultOrigins:
    """CORS should allow known local origins and block everything else."""

    @pytest.mark.parametrize("origin", [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:17493",
        "http://127.0.0.1:17493",
        "tauri://localhost",
        "https://tauri.localhost",
        "http://tauri.localhost",
    ])
    def test_allowed_origins(self, client, origin):
        headers = _get_with_origin(client, origin)
        assert headers.get("access-control-allow-origin") == origin

    @pytest.mark.parametrize("origin", [
        "http://evil.com",
        "http://localhost:9999",
        "https://attacker.example.com",
        "null",
    ])
    def test_blocked_origins(self, client, origin):
        headers = _get_with_origin(client, origin)
        assert "access-control-allow-origin" not in headers

    def test_preflight_allowed(self, client):
        headers = _preflight(client, "http://localhost:5173")
        assert headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_preflight_blocked(self, client):
        headers = _preflight(client, "http://evil.com")
        assert "access-control-allow-origin" not in headers

    def test_credentials_header_present(self, client):
        headers = _get_with_origin(client, "http://localhost:5173")
        assert headers.get("access-control-allow-credentials") == "true"


class TestCORSCustomOrigins:
    """VOICEBOX_CORS_ORIGINS env var should extend the allowlist."""

    def test_custom_origin_allowed(self, client_with_custom_origins):
        headers = _get_with_origin(client_with_custom_origins, "https://custom.example.com")
        assert headers.get("access-control-allow-origin") == "https://custom.example.com"

    def test_other_custom_origin_allowed(self, client_with_custom_origins):
        headers = _get_with_origin(client_with_custom_origins, "https://other.example.com")
        assert headers.get("access-control-allow-origin") == "https://other.example.com"

    def test_default_origins_still_work(self, client_with_custom_origins):
        headers = _get_with_origin(client_with_custom_origins, "http://localhost:5173")
        assert headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_unlisted_origin_still_blocked(self, client_with_custom_origins):
        headers = _get_with_origin(client_with_custom_origins, "http://evil.com")
        assert "access-control-allow-origin" not in headers


class TestCORSEnvVarParsing:
    """Edge cases for VOICEBOX_CORS_ORIGINS parsing."""

    def test_empty_env_var(self, monkeypatch):
        client = _build_client(monkeypatch, "")
        headers = _get_with_origin(client, "http://evil.com")
        assert "access-control-allow-origin" not in headers

    def test_whitespace_trimmed(self, monkeypatch):
        client = _build_client(monkeypatch, "  https://spaced.example.com  ")
        headers = _get_with_origin(client, "https://spaced.example.com")
        assert headers.get("access-control-allow-origin") == "https://spaced.example.com"

    def test_trailing_comma_ignored(self, monkeypatch):
        client = _build_client(monkeypatch, "https://one.example.com,")
        headers = _get_with_origin(client, "https://one.example.com")
        assert headers.get("access-control-allow-origin") == "https://one.example.com"
