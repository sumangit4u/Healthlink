"""
Database module for the doctor-agent service.
SQLAlchemy models + queries for the doctor store. This is the ONLY service that
owns the doctor database (SQLite by default, Azure Postgres via DATABASE_URL).
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from shared.config import Settings


logger = logging.getLogger("healthlink.doctor.database")

Base = declarative_base()


class DoctorModel(Base):
    """Doctor database model."""
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    specialty = Column(String(100), nullable=False)
    experience_years = Column(Integer, nullable=False)
    rating = Column(Float, nullable=False)
    availability = Column(String(100), nullable=False)
    location = Column(String(200), nullable=False)
    email = Column(String(200), nullable=True)
    phone = Column(String(20), nullable=True)
    qualifications = Column(String(500), nullable=True)
    languages = Column(String(200), nullable=True)
    consultation_type = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DatabaseManager:
    """Database manager for handling connections and sessions."""

    def __init__(self, settings: Settings):
        self.settings = settings

        if "sqlite" in settings.database_url:
            self.engine = create_engine(
                settings.database_url,
                echo=settings.db_echo,
                connect_args={"check_same_thread": False},
            )
        else:
            # Production (e.g. Azure Database for PostgreSQL): use a pool.
            self.engine = create_engine(
                settings.database_url,
                echo=settings.db_echo,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_pre_ping=True,
                pool_recycle=settings.db_pool_recycle_seconds,
            )

        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self._initialized = False

    def initialize_database(self) -> None:
        if not self._initialized:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created/verified")
            self._initialized = True

    def get_session(self) -> Session:
        return self.SessionLocal()

    @contextmanager
    def session_scope(self):
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}", exc_info=True)
            raise
        finally:
            session.close()


_db_manager: Optional[DatabaseManager] = None


def get_db_manager(settings: Settings) -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(settings)
        _db_manager.initialize_database()
    return _db_manager


def get_all_doctors(session: Session) -> List[DoctorModel]:
    return session.query(DoctorModel).all()


def get_doctors_by_specialty(session: Session, specialty: str) -> List[DoctorModel]:
    return session.query(DoctorModel).filter(
        DoctorModel.specialty.ilike(f"%{specialty}%")
    ).all()


def get_doctor_by_id(session: Session, doctor_id: int) -> Optional[DoctorModel]:
    return session.query(DoctorModel).filter(DoctorModel.id == doctor_id).first()


def get_specialties(session: Session) -> List[str]:
    rows = session.query(DoctorModel.specialty).distinct().all()
    return sorted({r[0] for r in rows})


def seed_doctors(session: Session, doctors_data: List[Dict[str, Any]]) -> None:
    """Seed the doctors table if empty."""
    existing_count = session.query(DoctorModel).count()
    if existing_count > 0:
        logger.info(f"Database already contains {existing_count} doctors, skipping seed")
        return

    # Only keep keys that map to real columns.
    columns = set(DoctorModel.__table__.columns.keys())
    for data in doctors_data:
        filtered = {k: v for k, v in data.items() if k in columns}
        session.add(DoctorModel(**filtered))

    session.commit()
    logger.info(f"Seeded database with {len(doctors_data)} doctors")
