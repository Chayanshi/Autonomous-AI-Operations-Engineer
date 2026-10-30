from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def ids(response):
    return [item["id"] for item in response.json()["items"]]


def test_first_page_contains_limit_items():
    response = client.get("/api/products?limit=3")

    assert response.status_code == 200
    assert ids(response) == [1, 2, 3]


def test_second_page_continues_after_the_first():
    assert ids(client.get("/api/products?offset=3&limit=3")) == [4, 5, 6]
