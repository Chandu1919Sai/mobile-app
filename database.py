from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# PostgreSQL DSN; no SQLite-only options like check_same_thread
DATABASE_URL = "postgresql://postgres:2026-d@localhost:5432/postgres"
engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()
