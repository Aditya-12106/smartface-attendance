"""
Database setup for the persistence API.

SQLite - this is a single-instance student project, no need for a managed
cloud database. It's one file (attendance.db) that SQLAlchemy talks to
the same way it would talk to Postgres, so swapping later is a one-line
change here if this ever needs to scale.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = "sqlite:///./attendance.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
