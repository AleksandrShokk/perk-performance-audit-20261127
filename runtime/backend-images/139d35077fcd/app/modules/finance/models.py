import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductCost(Base):
    """Append-only price history; the amount is encrypted, never stored as a float."""

    __tablename__ = "product_costs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    nm_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    barcode: Mapped[str] = mapped_column(String(100), primary_key=True, default="")
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    effective_from: Mapped[date] = mapped_column(primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CostImport(Base):
    __tablename__ = "cost_imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalExpense(Base):
    __tablename__ = "external_expenses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    expense_date: Mapped[date]
    currency: Mapped[str] = mapped_column(String(3))
    ciphertext: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceDay(Base):
    """Encrypted daily facts, grouped by SKU/variant and original cost date inside the payload."""

    __tablename__ = "finance_days"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(16), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text)


class TaxSetting(Base):
    """Versioned by date: a new regime applies from effective_from and never rewrites the past."""

    __tablename__ = "tax_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "regime IN ('none', 'usn_income', 'usn_income_expense', 'profit')", name="regime"
        ),
        CheckConstraint("income_base IN ('revenue', 'payout')", name="income_base"),
        CheckConstraint(
            "rate >= 0 AND rate <= 100 AND vat_rate >= 0 AND vat_rate <= 100", name="rates"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    effective_from: Mapped[date] = mapped_column(primary_key=True)
    regime: Mapped[str] = mapped_column(String(32))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    income_base: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Changes on every edit: report freshness depends on it, not only on inserts.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FinanceProjection(Base):
    __tablename__ = "finance_projections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"], ondelete="CASCADE"
        ),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    store_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source_run_id: Mapped[uuid.UUID] = mapped_column()
    format_version: Mapped[int] = mapped_column(Integer)
    legacy_date_from: Mapped[date | None] = mapped_column(Date)
    legacy_date_to: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
