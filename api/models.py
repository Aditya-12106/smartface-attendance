"""
Database tables.

Student        - one row per registered (name, group) pair
FaceDescriptor - one row per captured face sample (a student can have
                 several - one per photo/capture - matching is done
                 against all of them client-side)
AttendanceRecord - one row per "student X was present on date Y"
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    Time,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from database import Base


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    group_name = Column(String, nullable=False, default="", index=True)

    descriptors = relationship(
        "FaceDescriptor", back_populates="student", cascade="all, delete-orphan"
    )
    attendance_records = relationship("AttendanceRecord", back_populates="student")

    __table_args__ = (
        UniqueConstraint("name", "group_name", name="uq_student_name_group"),
    )


class FaceDescriptor(Base):
    __tablename__ = "face_descriptors"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    # face-api.js descriptors are 128-length float arrays. Stored as a
    # JSON-encoded string - there's no need for a dedicated vector column
    # type at this scale, and it keeps the schema simple.
    vector_json = Column(Text, nullable=False)

    student = relationship("Student", back_populates="descriptors")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    date = Column(Date, nullable=False)
    time = Column(Time, nullable=False)

    student = relationship("Student", back_populates="attendance_records")

    __table_args__ = (
        # a student can only be marked present once per day - enforced by
        # the database, not just application logic
        UniqueConstraint("student_id", "date", name="uq_attendance_student_date"),
    )


class AttendanceSession(Base):
    """A group/date session, including dates where everyone was absent."""

    __tablename__ = "attendance_sessions"

    id = Column(Integer, primary_key=True, index=True)
    group_name = Column(String, nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("group_name", "date", name="uq_attendance_session_group_date"),
    )
