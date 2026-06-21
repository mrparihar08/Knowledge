import os
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    JSON,
    Float,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import event

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tourist_safety.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30}
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite")
    else {},
    pool_pre_ping=True,
)

# Ensure SQLite enforces foreign key constraints
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DBUser(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    email = Column(String, unique=True, index=True, nullable=True)
    phone_number = Column(String, nullable=True)
    role = Column(String, index=True, nullable=False)

    full_name = Column(String, nullable=True)
    dob = Column(String, nullable=True)
    nationality = Column(String, nullable=True)
    identity_type = Column(String, nullable=True)
    identity_number = Column(String, unique=True, index=True, nullable=True)
    digital_tourist_id = Column(String, unique=True, index=True, nullable=True)
    trip_start = Column(String, nullable=True)
    trip_end = Column(String, nullable=True)
    itinerary = Column(JSON, nullable=True)
    emergency_contact = Column(String, nullable=True)
    document_path = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=True)

    is_verified = Column(Boolean, default=False, index=True)
    is_safe = Column(Boolean, default=True, index=True)
    chat_archived = Column(Boolean, default=False)

    bio = Column(String, nullable=True)
    profile_pic = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    emergency_alerts = relationship(
        "DBEmergencyAlert",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DBLocation(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    tourist_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


Index("ix_locations_tourist_timestamp", DBLocation.tourist_id, DBLocation.timestamp.desc())


class DBEmergencyAlert(Base):
    __tablename__ = "emergency_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    message = Column(String, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    user = relationship("DBUser", back_populates="emergency_alerts")


Index("ix_alerts_user_timestamp", DBEmergencyAlert.user_id, DBEmergencyAlert.timestamp.desc())


class DBChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    message = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    sender = relationship("DBUser", foreign_keys=[sender_id])
    recipient = relationship("DBUser", foreign_keys=[recipient_id])


Index("ix_chat_sender_timestamp", DBChatMessage.sender_id, DBChatMessage.timestamp.desc())
Index("ix_chat_recipient_timestamp", DBChatMessage.recipient_id, DBChatMessage.timestamp.desc())


class DBAuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    action = Column(String, nullable=False)
    target_id = Column(Integer, nullable=True)
    details = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    user = relationship("DBUser")


Index("ix_audit_user_timestamp", DBAuditLog.user_id, DBAuditLog.timestamp.desc())   


Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)