import base64
import json
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_liveness():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

def test_pubsub_push_invalid_format():
    response = client.post("/pubsub", json={})
    assert response.status_code == 400

def test_pubsub_push_no_data():
    response = client.post("/pubsub", json={"message": {}})
    assert response.status_code == 400

def test_pubsub_push_valid_format_unreachable_db():
    payload = json.dumps({"lat": 1.23, "lng": 4.56}).encode("utf-8")
    b64_data = base64.b64encode(payload).decode("utf-8")
    
    response = client.post("/pubsub", json={"message": {"data": b64_data}})
    assert response.status_code in [200, 500]
