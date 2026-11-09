"""
Database tables, defined as Python classes (SQLAlchemy ORM).

Two tables:
- Student: one row per registered student/face
- AttendanceRecord: one row per "student X was present on date Y"
"""

from sqlalchemy import Column, Integer, String, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    roll_no = Column(String, unique=True, nullable=False, index=True)

    attendance_records = relationship("AttendanceRecord", back_populates="student")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    date = Column(Date, nullable=False)
    confidence = Column(Integer, nullable=True)  # optional: match confidence 0-100

    student = relationship("Student", back_populates="attendance_records")

    __table_args__ = (
        # a student can only be marked present once per day - the database
        # itself enforces this, not just the frontend
        UniqueConstraint("student_id", "date", name="uq_student_date"),
    )
