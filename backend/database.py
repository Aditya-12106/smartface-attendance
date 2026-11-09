"""
Database setup for the attendance backend.

We use SQLite because this is a single-student-project scale app - no need
for a managed cloud database. SQLite is just a file on disk (attendance.db)
that SQLAlchemy talks to like any other database.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = "sqlite:///./attendance.db"

# check_same_thread=False is needed only for SQLite - it lets FastAPI's
# multiple request-handling threads share the same connection safely
# for our simple use case.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency: opens a DB session for a request, and guarantees
    it's closed afterward even if the request raises an error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
