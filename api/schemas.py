from datetime import date as date_type, time as time_type
from pydantic import BaseModel, ConfigDict


class StudentCreate(BaseModel):
    name: str
    group: str = ""
    descriptors: list[list[float]]  # one or more 128-length face vectors


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    group: str
    descriptors: list[list[float]]


class AttendanceCreate(BaseModel):
    student_id: int


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    name: str
    group: str
    date: date_type
    time: time_type


class MatrixOut(BaseModel):
    timestamps: list[str]
    rows: list[dict]
