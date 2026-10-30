from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_profile_email_is_normalised():
    response = client.get("/api/users/1/profile")

    assert response.status_code == 200
    assert response.json() == {"id": 1, "name": "Ada", "email": "ada@example.com"}


def test_profile_without_email_is_returned_with_null_email():
    response = client.get("/api/users/2/profile")

    assert response.status_code == 200
    assert response.json() == {"id": 2, "name": "Grace", "email": None}


def test_unknown_user_is_404():
    assert client.get("/api/users/99/profile").status_code == 404
