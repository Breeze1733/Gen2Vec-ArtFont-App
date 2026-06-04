import os

# Test environment: skip the per-request wait for ComfyUI readiness so
# tests don't hang for 5 min when no ComfyUI is running.
os.environ.setdefault("COMFYUI_READY_WAIT_SECONDS", "0")

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "txt2img-api"}


def test_generate_returns_image_and_metadata() -> None:
    response = client.post(
        "/api/v1/txt2img",
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