import importlib
import sys

import pytest
from fastapi.testclient import TestClient


def load_app(monkeypatch: pytest.MonkeyPatch, page_size: str | None):
    if page_size is None:
        monkeypatch.delenv("PAGE_SIZE", raising=False)
    else:
        monkeypatch.setenv("PAGE_SIZE", page_size)
    sys.modules.pop("app", None)
    return importlib.import_module("app").app


def test_service_starts_with_default_page_size_when_unset(monkeypatch: pytest.MonkeyPatch):
    client = TestClient(load_app(monkeypatch, None))

    response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {"page_size": 20}


def test_configured_page_size_is_respected(monkeypatch: pytest.MonkeyPatch):
    client = TestClient(load_app(monkeypatch, "50"))

    assert client.get("/api/settings").json() == {"page_size": 50}
