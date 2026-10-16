import os
os.environ["ENGINE_DATABASE_URL"] = "sqlite:///./test_geodiscover.db"
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["DEMO_ADMIN_EMAIL"] = "test@example.com"
os.environ["DEMO_ADMIN_PASSWORD"] = "TestPassword123!"

# Blank every provider credential before app.config is imported.
# Settings reads backend/.env, so without this the suite picks up real API keys and
# a test that posts a sweep will spend actual money against Google and AWS.
# Environment variables take precedence over the .env file, so setting them to empty
# strings makes the tests credential-free and deterministic regardless of local setup.
for _credential in (
    "GOOGLE_MAPS_API_KEY",
    "HERE_API_KEY",
    "AWS_LOCATION_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
):
    os.environ[_credential] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from discovery_engine.database import Base, get_db
from discovery_engine.main import app
from discovery_engine.models import User, UserRole
from discovery_engine.auth import hash_password

TEST_URL = "sqlite:///./test_geodiscover.db"
engine = create_engine(TEST_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_db

@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    db.add(User(email="test@example.com", full_name="Test Admin", password_hash=hash_password("TestPassword123!"), role=UserRole.SUPER_ADMIN))
    db.commit(); db.close()
    yield

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def token(client):
    response = client.post("/api/v1/auth/login", json={"email":"test@example.com","password":"TestPassword123!"})
    assert response.status_code == 200
    return response.json()["access_token"]

@pytest.fixture
def headers(token):
    return {"Authorization": f"Bearer {token}"}
