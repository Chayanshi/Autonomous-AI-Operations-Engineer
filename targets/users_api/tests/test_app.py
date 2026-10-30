from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_get_users_returns_healthy_json_response():
    response = client.get("/api/users")

    assert response.status_code == 200
    assert response.json() == {"users": []}
