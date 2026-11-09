import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db

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

SAMPLE_DESCRIPTOR = [0.1] * 128


def test_register_student():
    res = client.post(
        "/students",
        json={"name": "Test Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Test Student"
    assert data["group"] == "B2"
    assert len(data["descriptors"]) == 1
    assert len(data["descriptors"][0]) == 128


def test_registering_same_student_again_appends_descriptors():
    client.post(
        "/students",
        json={"name": "Test Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
    )
    res = client.post(
        "/students",
        json={"name": "Test Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR] * 7},
    )
    assert res.status_code == 201
    assert len(res.json()["descriptors"]) == 8  # 1 + 7, not a duplicate row


def test_different_group_is_a_different_student_record():
    client.post(
        "/students",
        json={"name": "Test Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
    )
    client.post(
        "/students",
        json={"name": "Test Student", "group": "B3", "descriptors": [SAMPLE_DESCRIPTOR]},
    )
    res = client.get("/students")
    assert len(res.json()) == 2


def test_mark_attendance():
    student = client.post(
        "/students",
        json={"name": "Test Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
    ).json()
    res = client.post("/attendance", json={"student_id": student["id"]})
    assert res.status_code == 201
    assert res.json()["name"] == "Test Student"


def test_cannot_mark_attendance_twice_same_day():
    student = client.post(
        "/students",
        json={"name": "Test Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
    ).json()
    client.post("/attendance", json={"student_id": student["id"]})
    res = client.post("/attendance", json={"student_id": student["id"]})
    assert res.status_code == 409


def test_mark_attendance_unknown_student():
    res = client.post("/attendance", json={"student_id": 9999})
    assert res.status_code == 404


def test_attendance_matrix():
    student = client.post(
        "/students",
        json={"name": "Test Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
    ).json()
    client.post("/attendance", json={"student_id": student["id"]})
    res = client.get("/attendance/matrix", params={"group": "B2"})
    assert res.status_code == 200
    data = res.json()
    assert len(data["timestamps"]) == 1
    assert data["rows"][0]["Name"] == "Test Student"


def test_export_excel_returns_file():
    student = client.post(
        "/students",
        json={"name": "Test Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
    ).json()
    client.post("/attendance", json={"student_id": student["id"]})
    res = client.get("/attendance/export", params={"group": "B2"})
    assert res.status_code == 200
    assert "spreadsheet" in res.headers["content-type"]


def test_import_current_api_backup_merges_and_is_idempotent():
    payload = {
        "version": 2,
        "students": [
            {"id": 41, "name": "Imported Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]}
        ],
        "attendance": [
            {"id": 90, "student_id": 41, "name": "Imported Student", "group": "B2", "date": "2026-10-01", "time": "09:15:00"}
        ],
        "attendance_sessions": [{"group": "B2", "date": "2026-10-01"}],
    }

    first = client.post("/import/all", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["students_added"] == 1
    assert first.json()["descriptors_added"] == 1
    assert first.json()["attendance_added"] == 1
    assert first.json()["sessions_added"] == 1

    second = client.post("/import/all", json=payload)
    assert second.status_code == 200, second.text
    assert second.json()["students_added"] == 0
    assert second.json()["descriptors_added"] == 0
    assert second.json()["attendance_added"] == 0
    assert second.json()["attendance_skipped"] == 1
    assert second.json()["sessions_added"] == 0

    students = client.get("/students").json()
    assert len(students) == 1
    assert len(students[0]["descriptors"]) == 1
    matrix = client.get("/attendance/matrix", params={"group": "B2"}).json()
    assert matrix["timestamps"] == ["2026-10-01"]
    assert matrix["rows"][0]["2026-10-01"] == "p"


def test_import_current_backup_merges_case_insensitive_existing_student():
    client.post(
        "/students",
        json={"name": "Existing Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
    )
    new_descriptor = [0.2] * 128
    payload = {
        "students": [
            {"id": 7, "name": "existing student", "group": "b2", "descriptors": [new_descriptor]}
        ],
        "attendance": [],
    }
    response = client.post("/import/all", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["students_added"] == 0
    assert response.json()["students_merged"] == 1
    assert response.json()["descriptors_added"] == 1
    students = client.get("/students").json()
    assert len(students) == 1
    assert len(students[0]["descriptors"]) == 2


def test_import_legacy_browser_backup_includes_group_sheet_dates():
    payload = {
        "version": 1,
        "students": [
            {"name": "Present Student", "group": "B2", "descriptors": [SAMPLE_DESCRIPTOR]},
            {"name": "Absent Student", "group": "B2", "descriptors": []},
        ],
        "attendanceByDate": {
            "2026-10-02": [
                {"Name": "Present Student", "Group": "B2", "Time": "09:30:00 AM", "Status": "Present"}
            ]
        },
        "groupSheets": {
            "B2": {
                "timestamps": ["2026-10-02T08:00:00.000Z", "2026-10-03T08:00:00.000Z"],
                "rows": [
                    {"Name": "Present Student", "2026-10-02T08:00:00.000Z": "p", "2026-10-03T08:00:00.000Z": "a"},
                    {"Name": "Absent Student", "2026-10-02T08:00:00.000Z": "a", "2026-10-03T08:00:00.000Z": "a"},
                ],
            }
        },
    }
    response = client.post("/import/all", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["attendance_added"] == 1
    matrix = client.get("/attendance/matrix", params={"group": "B2"}).json()
    assert matrix["timestamps"] == ["2026-10-02", "2026-10-03"]
    rows = {row["Name"]: row for row in matrix["rows"]}
    assert rows["Present Student"]["2026-10-02"] == "p"
    assert rows["Absent Student"]["2026-10-02"] == "a"
    assert rows["Absent Student"]["2026-10-03"] == "a"


def test_import_rejects_invalid_face_descriptor_without_partial_changes():
    payload = {
        "students": [
            {"id": 1, "name": "Invalid Student", "group": "B2", "descriptors": [[0.1, 0.2]]}
        ],
        "attendance": [],
    }
    response = client.post("/import/all", json=payload)
    assert response.status_code == 400
    assert "128" in response.json()["detail"]
    assert client.get("/students").json() == []


def test_import_legacy_unassigned_group_without_creating_duplicate_student():
    payload = {
        "version": 1,
        "students": [{"name": "Solo Student", "group": "", "descriptors": []}],
        "attendanceByDate": {},
        "groupSheets": {
            "Unassigned": {
                "timestamps": ["2026-10-04T08:00:00.000Z"],
                "rows": [{"Name": "Solo Student", "2026-10-04T08:00:00.000Z": "a"}],
            }
        },
    }
    response = client.post("/import/all", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["students_added"] == 1
    assert len(client.get("/students").json()) == 1
    matrix = client.get("/attendance/matrix", params={"group": "Unassigned"}).json()
    assert matrix["timestamps"] == ["2026-10-04"]
    assert matrix["rows"] == [{"Name": "Solo Student", "2026-10-04": "a"}]
