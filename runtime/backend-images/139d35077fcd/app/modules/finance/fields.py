"""WB report facts, before accounting rules and product costs are applied.

Keep signed source values: a correction may reverse an expense. Do not sum
these fields into profit or subtract them all from for_pay; some overlap.
"""

from typing import Literal

from pydantic import BaseModel, Field, computed_field

DATA_VERSION = 3

# Only fields needed for financial reconciliation and SKU/cost matching are
# requested. Buyer contacts, supplier INNs and bank information are excluded.
AMOUNT_FIELDS = {
    "retail_amount": "retailAmount",
    "for_pay": "forPay",
    "acquiring_fee": "acquiringFee",
    "acquiring_percent": "acquiringPercent",
    "retail_price": "retailPrice",
    "retail_price_with_discount": "retailPriceWithDisc",
    "sales_commission": "ppvzSalesCommission",
    "delivery_service": "deliveryService",
    "paid_storage": "paidStorage",
    "paid_acceptance": "paidAcceptance",
    "penalty": "penalty",
    "deduction": "deduction",
    "additional_payment": "additionalPayment",
    "rebill_logistic_cost": "rebillLogisticCost",
    "pickup_reward": "ppvzReward",
    "wb_remuneration": "vw",
    "wb_remuneration_vat": "vwNds",
    "cashback_amount": "cashbackAmount",
    "cashback_discount": "cashbackDiscount",
    "payment_schedule": "paymentSchedule",
    "cashback_commission_change": "cashbackCommissionChange",
    "installment_cofinancing_amount": "installmentCofinancingAmount",
}

REFERENCE_FIELDS = {
    "bonus_type_name": ("bonusTypeName", 2000),
    "vendor_code": ("vendorCode", 500),
    "size": ("techSize", 500),
    "barcode": ("sku", 100),
    "warehouse_name": ("officeName", 500),
    "order_date": ("orderDt", 64),
    "sale_date": ("saleDt", 64),
    "sale_reference": ("srid", 100),
}


class FinanceDetails(BaseModel):
    """Missing historical values remain null; money is an exact decimal string."""

    data_version: Literal[1, 2, 3] = Field(
        default=1,
        description="1: original fields; 2: extended amounts; 3: expense classification fields.",
    )
    bonus_type_name: str | None = None
    payment_schedule: str | None = None
    acquiring_percent: str | None = None
    cashback_discount: str | None = None
    vendor_code: str | None = None
    size: str | None = None
    barcode: str | None = None
    warehouse_name: str | None = None
    order_date: str | None = None
    sale_date: str | None = None
    sale_reference: str | None = None
    retail_price: str | None = None
    retail_price_with_discount: str | None = None
    sales_commission: str | None = None
    delivery_service: str | None = None
    paid_storage: str | None = None
    paid_acceptance: str | None = None
    penalty: str | None = None
    deduction: str | None = None
    additional_payment: str | None = None
    rebill_logistic_cost: str | None = None
    pickup_reward: str | None = None
    wb_remuneration: str | None = None
    wb_remuneration_vat: str | None = None
    cashback_amount: str | None = None
    cashback_commission_change: str | None = None
    installment_cofinancing_amount: str | None = None

    @computed_field(description="Requested amount fields absent or null in this report row.")
    @property
    def missing_amount_fields(self) -> list[str]:
        return [name for name in AMOUNT_FIELDS if getattr(self, name, None) is None]

    @computed_field(
        description="Completeness of requested row amounts, not of profit or all expenses."
    )
    @property
    def requested_amounts_complete(self) -> bool:
        return self.data_version == DATA_VERSION and not self.missing_amount_fields
