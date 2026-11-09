"""
Tests for the attendance API.

Uses a separate in-memory SQLite database for tests, so running tests
never touches your real attendance.db.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
import models
from database import Base, get_db

# In-memory test database - wiped clean every test run.
# StaticPool makes all connections share the same in-memory DB instead of
# each getting its own empty one (SQLite's default in-memory behavior).
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def test_register_student():
    response = client.post("/students", json={"name": "Test Student", "roll_no": "CS101"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Student"
    assert data["roll_no"] == "CS101"
    assert "id" in data


def test_cannot_register_duplicate_roll_no():
    client.post("/students", json={"name": "Test Student", "roll_no": "CS101"})
    response = client.post("/students", json={"name": "Someone Else", "roll_no": "CS101"})
    assert response.status_code == 400


def test_mark_attendance():
    student = client.post("/students", json={"name": "Test Student", "roll_no": "CS101"}).json()
    response = client.post(
        "/attendance", json={"student_id": student["id"], "date": "2026-09-12"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["student_id"] == student["id"]
    assert data["date"] == "2026-09-12"


def test_cannot_mark_attendance_twice_same_day():
    student = client.post("/students", json={"name": "Test Student", "roll_no": "CS101"}).json()
    client.post("/attendance", json={"student_id": student["id"], "date": "2026-09-12"})
    response = client.post(
        "/attendance", json={"student_id": student["id"], "date": "2026-09-12"}
    )
    assert response.status_code == 409


def test_mark_attendance_unknown_student_fails():
    response = client.post("/attendance", json={"student_id": 9999, "date": "2026-09-12"})
    assert response.status_code == 404


def test_get_attendance_filtered_by_date():
    student = client.post("/students", json={"name": "Test Student", "roll_no": "CS101"}).json()
    client.post("/attendance", json={"student_id": student["id"], "date": "2026-09-12"})
    response = client.get("/attendance", params={"date": "2026-09-12"})
    assert response.status_code == 200
    assert len(response.json()) == 1
