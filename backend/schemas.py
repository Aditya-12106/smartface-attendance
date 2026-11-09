"""
Pydantic schemas: define the shape of data going in and out of the API.

These are separate from the SQLAlchemy models on purpose - the models
describe the database table, the schemas describe the JSON contract with
the frontend. Keeping them separate means you can change your DB structure
without silently changing your API, and vice versa.
"""

from datetime import date as date_type
from pydantic import BaseModel, Field, ConfigDict


class StudentCreate(BaseModel):
    name: str = Field(..., min_length=1)
    roll_no: str = Field(..., min_length=1)


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    roll_no: str


class AttendanceCreate(BaseModel):
    student_id: int
    date: date_type | None = None  # defaults to today if omitted
    confidence: int | None = Field(default=None, ge=0, le=100)


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    date: date_type
    confidence: int | None
