from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "word2pic"}


def test_generate_returns_image_and_metadata() -> None:
    response = client.post(
        "/api/v1/generate",
        json={
            "prompt": "晨曦之城",
            "negative_prompt": "模糊, 断裂",
            "resolution": "1024 x 1024",
            "seed": 42,
            "style": "neon",
            "format": "PNG",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["image_base64"].startswith("data:image/png;base64,")
    assert payload["image_name"].endswith(".png")
    assert payload["metadata"]["prompt"] == "晨曦之城"
    assert payload["metadata"]["seed"] == 42