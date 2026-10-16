from fastapi.testclient import TestClient

from app.main import app


def test_login_rate_limit_per_email():
    c = TestClient(app)
    codes = [c.post("/api/auth/login", json={"email": "ratelimit@demo.civicbridge.local", "password": "x" * 12}).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8 and codes[8] == 429
