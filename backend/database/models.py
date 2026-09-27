from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )

    date_of_birth: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True
    )

    gender: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )


class Condition(Base):
    __tablename__ = "conditions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False
    )

    condition: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    onset: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )


class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False
    )

    medication: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )


class Allergy(Base):
    __tablename__ = "allergies"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False
    )

    allergy: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False
    )

    type: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    date: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )


class Encounter(Base):
    __tablename__ = "encounters"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False
    )

    type: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    start: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )


class Referral(Base):
    __tablename__ = "referrals"

    referral_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.patient_id"),
        nullable=False
    )

    department: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )