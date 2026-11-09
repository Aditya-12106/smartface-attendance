"""
Persistence API for SmartFace Attendance.

This backend does ONE job: store students (with their face descriptors)
and attendance records in a real database, and serve them back over a
documented REST API. Face recognition itself still happens entirely in
the browser via face-api.js - this backend never sees a camera frame or
an image, only the numeric descriptor arrays face-api.js already computed.

Why it's split this way: face-api.js runs against the *visitor's own*
webcam through browser APIs, which is what makes the deployed GitHub
Pages demo actually work for anyone who opens the link. A server-side
recognition backend (see /backend/main.py) would need the *server's*
webcam, which doesn't exist on a cloud host - fine for a local demo, not
for something you can hand a recruiter as a live link.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Then open http://127.0.0.1:8000/docs
"""

import io
import json
import math
from datetime import date as date_type, datetime, time as time_type

import pandas as pd
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import models
import schemas
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="SmartFace Attendance API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _student_to_out(student: models.Student) -> dict:
    return {
        "id": student.id,
        "name": student.name,
        "group": student.group_name,
        "descriptors": [json.loads(d.vector_json) for d in student.descriptors],
    }


def _attendance_to_out(record: models.AttendanceRecord) -> dict:
    return {
        "id": record.id,
        "student_id": record.student_id,
        "name": record.student.name,
        "group": record.student.group_name,
        "date": record.date,
        "time": record.time,
    }


@app.post("/students", response_model=schemas.StudentOut, status_code=201)
def register_student(payload: schemas.StudentCreate, db: Session = Depends(get_db)):
    """
    Register a student, or add more face samples to an existing
    (name, group) pair - matches the "Capture 8 Photos" flow which can be
    called multiple times for the same student.
    """
    name = payload.name.strip()
    group = payload.group.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Student name is required")
    if not payload.descriptors:
        raise HTTPException(status_code=400, detail="At least one face descriptor is required")

    student = (
        db.query(models.Student)
        .filter_by(name=name, group_name=group)
        .first()
    )
    if not student:
        student = models.Student(name=name, group_name=group)
        db.add(student)
        db.flush()  # assigns student.id before we attach descriptors

    for vector in payload.descriptors:
        db.add(
            models.FaceDescriptor(
                student_id=student.id, vector_json=json.dumps(vector)
            )
        )

    db.commit()
    db.refresh(student)
    return _student_to_out(student)


@app.get("/students", response_model=list[schemas.StudentOut])
def list_students(group: str = "", db: Session = Depends(get_db)):
    """List all students (with descriptors, so the frontend can match
    against them), optionally filtered by group."""
    query = db.query(models.Student)
    if group:
        query = query.filter(models.Student.group_name.ilike(group))
    return [_student_to_out(s) for s in query.all()]


@app.post("/attendance", response_model=schemas.AttendanceOut, status_code=201)
def mark_attendance(payload: schemas.AttendanceCreate, db: Session = Depends(get_db)):
    """Mark a student present today. Rejects a duplicate for the same day -
    enforced by the database's UniqueConstraint, not just this check."""
    student = db.query(models.Student).filter_by(id=payload.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="student not found")

    now = datetime.now()
    record = models.AttendanceRecord(
        student_id=student.id, date=now.date(), time=now.time().replace(microsecond=0)
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"{student.name} is already marked present today",
        )
    db.refresh(record)
    return _attendance_to_out(record)


@app.get("/attendance/today", response_model=list[schemas.AttendanceOut])
def attendance_today(group: str = "", db: Session = Depends(get_db)):
    query = (
        db.query(models.AttendanceRecord)
        .join(models.Student)
        .filter(models.AttendanceRecord.date == date_type.today())
    )
    if group:
        query = query.filter(models.Student.group_name.ilike(group))
    return [_attendance_to_out(r) for r in query.all()]


@app.get("/attendance/matrix", response_model=schemas.MatrixOut)
def attendance_matrix(group: str = Query(...), db: Session = Depends(get_db)):
    """
    Present/absent matrix for a group: one column per date attendance was
    taken, one row per student who belongs to the group or has ever been
    marked present in it.
    """
    group_filter = "" if group.strip().casefold() == "unassigned" else group
    students = (
        db.query(models.Student)
        .filter(models.Student.group_name.ilike(group_filter))
        .all()
    )
    records = (
        db.query(models.AttendanceRecord)
        .join(models.Student)
        .filter(models.Student.group_name.ilike(group_filter))
        .all()
    )

    all_students = {s.id: s.name for s in students}
    for r in records:
        all_students.setdefault(r.student_id, r.student.name)

    session_dates = {
        session.date.isoformat()
        for session in db.query(models.AttendanceSession)
        .filter(models.AttendanceSession.group_name.ilike(group_filter))
        .all()
    }
    dates = sorted({r.date.isoformat() for r in records} | session_dates)
    present = {(r.student_id, r.date.isoformat()) for r in records}

    rows = []
    for student_id, name in sorted(all_students.items(), key=lambda kv: kv[1].lower()):
        row = {"Name": name}
        for d in dates:
            row[d] = "p" if (student_id, d) in present else "a"
        rows.append(row)

    return {"timestamps": dates, "rows": rows}


@app.get("/attendance/export")
def export_group_excel(group: str = Query(...), db: Session = Depends(get_db)):
    """Generate an Excel workbook for a group on demand from the database,
    rather than maintaining a separate file that could drift out of sync."""
    matrix = attendance_matrix(group=group, db=db)
    if not matrix["rows"]:
        raise HTTPException(status_code=404, detail="No attendance data for this group")

    df = pd.DataFrame(matrix["rows"])
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    safe_group = "".join(c if c.isalnum() else "_" for c in group) or "group"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=Attendance_{safe_group}.xlsx"},
    )


@app.get("/export/all")
def export_all(db: Session = Depends(get_db)):
    """Full JSON dump of students and attendance - used by the 'Export
    Dataset' button as a backup/portability option."""
    students = db.query(models.Student).all()
    records = db.query(models.AttendanceRecord).all()
    sessions = db.query(models.AttendanceSession).all()
    return {
        "version": 2,
        "exported_at": datetime.now().isoformat(),
        "students": [_student_to_out(s) for s in students],
        "attendance": [_attendance_to_out(r) for r in records],
        "attendance_sessions": [
            {"group": session.group_name, "date": session.date.isoformat()}
            for session in sessions
        ],
    }



def _parse_import_date(value) -> date_type:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_type):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Attendance date must be an ISO date or datetime string")
    raw = value.strip()
    try:
        return date_type.fromisoformat(raw[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid attendance date: {raw}") from exc


def _parse_import_time(value) -> time_type:
    if isinstance(value, time_type):
        return value.replace(microsecond=0)
    if not isinstance(value, str) or not value.strip():
        return time_type(0, 0, 0)
    raw = value.strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(raw, fmt).time().replace(microsecond=0)
        except ValueError:
            continue
    try:
        return time_type.fromisoformat(raw).replace(microsecond=0)
    except ValueError as exc:
        raise ValueError(f"Invalid attendance time: {raw}") from exc


def _normalise_identity(name: str, group: str) -> tuple[str, str]:
    return name.strip().casefold(), group.strip().casefold()


def _validate_descriptors(raw_descriptors, student_name: str) -> list[list[float]]:
    if raw_descriptors is None:
        return []
    if not isinstance(raw_descriptors, list):
        raise ValueError(f"Descriptors for {student_name} must be a list")
    validated = []
    for vector_index, vector in enumerate(raw_descriptors):
        if not isinstance(vector, list) or len(vector) != 128:
            raise ValueError(
                f"Descriptor {vector_index + 1} for {student_name} must contain exactly 128 numbers"
            )
        clean_vector = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Descriptors for {student_name} must contain finite numbers")
            clean_vector.append(float(value))
        validated.append(clean_vector)
    return validated


@app.post("/import/all")
def import_all(payload: dict, db: Session = Depends(get_db)):
    """Merge a SmartFace JSON backup into SQLite.

    Supports the current API export format (version 2) and the legacy
    browser-localStorage export format (version 1). Existing students and
    attendance are retained; matching students gain only new descriptors,
    and duplicate attendance entries are skipped.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Dataset must be a JSON object")
    source_students = payload.get("students", [])
    if not isinstance(source_students, list):
        raise HTTPException(status_code=400, detail="Dataset students must be a list")

    is_legacy = any(key in payload for key in ("attendanceByDate", "groupSheets"))
    if is_legacy:
        if not isinstance(payload.get("attendanceByDate", {}), dict):
            raise HTTPException(status_code=400, detail="attendanceByDate must be an object")
        if not isinstance(payload.get("groupSheets", {}), dict):
            raise HTTPException(status_code=400, detail="groupSheets must be an object")
    else:
        if not isinstance(payload.get("attendance", []), list):
            raise HTTPException(status_code=400, detail="Dataset attendance must be a list")
        if not isinstance(payload.get("attendance_sessions", []), list):
            raise HTTPException(status_code=400, detail="attendance_sessions must be a list")

    imported_by_source_id: dict[str, int] = {}
    imported_by_identity: dict[tuple[str, str], int] = {}
    students_added = 0
    students_merged = 0
    descriptors_added = 0
    attendance_added = 0
    attendance_skipped = 0
    sessions_added = 0
    descriptor_keys_by_student: dict[int, set[str]] = {}

    try:
        def get_or_create_student(name_value, group_value="", descriptors_value=None):
            nonlocal students_added, students_merged, descriptors_added
            if not isinstance(name_value, str) or not name_value.strip():
                raise ValueError("Every imported student must have a non-empty name")
            if group_value is None:
                group_value = ""
            if not isinstance(group_value, str):
                raise ValueError("Student group must be a string")
            name = name_value.strip()
            group = group_value.strip()
            descriptors = _validate_descriptors(descriptors_value, name)
            identity = _normalise_identity(name, group)
            student = None
            local_id = imported_by_identity.get(identity)
            if local_id is not None:
                student = db.query(models.Student).filter_by(id=local_id).first()
            if student is None:
                student = (
                    db.query(models.Student)
                    .filter(
                        func.lower(models.Student.name) == identity[0],
                        func.lower(models.Student.group_name) == identity[1],
                    )
                    .first()
                )
            if student is None:
                student = models.Student(name=name, group_name=group)
                db.add(student)
                db.flush()
                students_added += 1
            else:
                students_merged += 1

            existing_vectors = descriptor_keys_by_student.get(student.id)
            if existing_vectors is None:
                existing_vectors = set()
                for descriptor in student.descriptors:
                    try:
                        existing_vectors.add(
                            json.dumps(json.loads(descriptor.vector_json), separators=(",", ":"))
                        )
                    except (TypeError, ValueError):
                        continue
                descriptor_keys_by_student[student.id] = existing_vectors
            for vector in descriptors:
                vector_key = json.dumps(vector, separators=(",", ":"))
                if vector_key in existing_vectors:
                    continue
                db.add(models.FaceDescriptor(student_id=student.id, vector_json=vector_key))
                existing_vectors.add(vector_key)
                descriptors_added += 1
            imported_by_identity[identity] = student.id
            return student

        # Import students first so attendance can map source IDs to local IDs.
        seen_source_ids = set()
        for source_student in source_students:
            if not isinstance(source_student, dict):
                raise ValueError("Each student entry must be an object")
            source_id = source_student.get("id")
            if source_id is not None:
                source_id_key = str(source_id)
                if source_id_key in seen_source_ids:
                    raise ValueError(f"Duplicate student ID in dataset: {source_id_key}")
                seen_source_ids.add(source_id_key)
            student = get_or_create_student(
                source_student.get("name"),
                source_student.get("group", source_student.get("group_name", "")),
                source_student.get("descriptors", []),
            )
            if source_id is not None:
                imported_by_source_id[str(source_id)] = student.id

        # Current API export attendance: rows point to source student IDs.
        normalised_attendance = []
        if not is_legacy:
            for entry in payload.get("attendance", []):
                if not isinstance(entry, dict):
                    raise ValueError("Each attendance entry must be an object")
                source_student_id = entry.get("student_id")
                local_student_id = imported_by_source_id.get(str(source_student_id))
                if local_student_id is None:
                    name = entry.get("name")
                    group = entry.get("group", "")
                    if isinstance(name, str) and name.strip():
                        local_student_id = imported_by_identity.get(_normalise_identity(name, group or ""))
                if local_student_id is None:
                    raise ValueError(f"Attendance references an unknown imported student ID: {source_student_id}")
                normalised_attendance.append((
                    local_student_id,
                    _parse_import_date(entry.get("date")),
                    _parse_import_time(entry.get("time")),
                ))

            for session in payload.get("attendance_sessions", []):
                if not isinstance(session, dict):
                    raise ValueError("Each attendance session must be an object")
                group = session.get("group", session.get("group_name", ""))
                if group is None:
                    group = ""
                if not isinstance(group, str):
                    raise ValueError("Attendance session group must be a string")
                group = "" if group.strip().casefold() == "unassigned" else group.strip()
                session_date = _parse_import_date(session.get("date"))
                existing_session = db.query(models.AttendanceSession).filter_by(
                    group_name=group, date=session_date
                ).first()
                if not existing_session:
                    db.add(models.AttendanceSession(group_name=group, date=session_date))
                    sessions_added += 1
        else:
            # Legacy export format: attendanceByDate contains present rows.
            for date_key, entries in payload.get("attendanceByDate", {}).items():
                if not isinstance(entries, list):
                    raise ValueError(f"Attendance entries for {date_key} must be a list")
                entry_date = _parse_import_date(date_key)
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("Each legacy attendance entry must be an object")
                    status = str(entry.get("Status", entry.get("status", "Present"))).strip().casefold()
                    if status not in ("present", "p", ""):
                        continue
                    name = entry.get("Name", entry.get("name"))
                    group = entry.get("Group", entry.get("group", "")) or ""
                    student = get_or_create_student(name, group, [])
                    normalised_attendance.append((
                        student.id,
                        entry_date,
                        _parse_import_time(entry.get("Time", entry.get("time"))),
                    ))

            # Legacy group sheets hold a roster and p/a cells. Import every
            # date as a session so all-absent dates remain visible in the matrix.
            for group_name, sheet in payload.get("groupSheets", {}).items():
                if not isinstance(sheet, dict):
                    raise ValueError(f"Group sheet for {group_name} must be an object")
                group = str(group_name).strip()
                if not group:
                    raise ValueError("Group sheet name cannot be empty")
                stored_group = "" if group.casefold() == "unassigned" else group
                timestamps = sheet.get("timestamps", [])
                rows = sheet.get("rows", [])
                if not isinstance(timestamps, list) or not isinstance(rows, list):
                    raise ValueError(f"Group sheet for {group} has invalid timestamps or rows")
                parsed_dates = [_parse_import_date(value) for value in timestamps]
                for session_date in parsed_dates:
                    exists = db.query(models.AttendanceSession).filter_by(
                        group_name=stored_group, date=session_date
                    ).first()
                    if not exists:
                        db.add(models.AttendanceSession(group_name=stored_group, date=session_date))
                        sessions_added += 1
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError(f"Group sheet rows for {group} must be objects")
                    name = row.get("Name", row.get("name"))
                    student = get_or_create_student(name, stored_group, [])
                    for timestamp, session_date in zip(timestamps, parsed_dates):
                        cell = str(row.get(timestamp, "a")).strip().casefold()
                        if cell in ("p", "present"):
                            normalised_attendance.append((student.id, session_date, time_type(0, 0, 0)))

        # De-duplicate imported rows and preserve existing attendance.
        seen_attendance = set()
        for student_id, record_date, record_time in normalised_attendance:
            key = (student_id, record_date)
            if key in seen_attendance:
                attendance_skipped += 1
                continue
            seen_attendance.add(key)
            exists = db.query(models.AttendanceRecord).filter_by(
                student_id=student_id, date=record_date
            ).first()
            if exists:
                attendance_skipped += 1
                continue
            db.add(models.AttendanceRecord(
                student_id=student_id, date=record_date, time=record_time
            ))
            attendance_added += 1

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except (ValueError, TypeError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Dataset import failed: {exc}") from exc

    return {
        "students_added": students_added,
        "students_merged": students_merged,
        "descriptors_added": descriptors_added,
        "attendance_added": attendance_added,
        "attendance_skipped": attendance_skipped,
        "sessions_added": sessions_added,
    }
