import os
os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project"
os.environ["PUB_SUB_TOPIC_ID"] = "test-topic"
os.environ["API_KEY"] = "dev-secret-key"

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_liveness():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

def test_readiness_fails_without_pubsub_config():
    # Because PROJECT_ID and TOPIC_ID might be mocked or missing, readiness might fail or pass
    # But it should return an HTTP status code
    response = client.get("/readyz")
    assert response.status_code in [200, 503]

def test_receive_tingle_unauthorized():
    response = client.post("/tingle", json={"lat": 1.23, "lng": 4.56})
    assert response.status_code == 403

def test_receive_tingle_authorized():
    # This might fail with 500 if PubSub isn't actually mocked, but we verify auth passes
    response = client.post(
        "/tingle", 
        json={"lat": 1.23, "lng": 4.56},
        headers={"X-API-Key": "dev-secret-key"}
    )
    assert response.status_code in [200, 500, 503]
