"""Exact accrual ledger: actual charges once; buyer prices separately from seller income."""

from datetime import date
from decimal import Decimal

from app.modules.finance.precision import money, money_precision

# Match stable provider names from /types, never tenant-specific numeric ids or text guesses.
SERVICE_GROUPS = {
    "fees": ("Acquiring SaleCommission RfbsDomesticAgentFee RfbsGlobalAgentFee RfbsServiceFee"),
    "logistics": (
        "BackwardShipment Cancellation ClientReturn CrossDock "
        "CrossDockPickUpCourierDelivery Drop-Off Drop-Off_Agent Fulfillment "
        "LastMile LastMileCourier LastMilePickUpPoint Logistic PartialReturn ReturnFlowLogistic "
        "Pick-Up PickUpCourierArrangement PickUpCourierDelivery "
        "PickUpPointReturnAcceptance PreparingToReturn SellerReturns Shipment "
        "RfbsDomesticDelivery RfbsEasyReturn RfbsGlobalDelivery ClickAndCollect "
        "PackageUnitProcessing DeliveryToHandoverPlaceByOzon "
        "InternationalLogisticDelta OzonGlobalLogisticsDelivery "
        "CourierPickUpByOzon CourierPickUpReinvoice "
        "SellerReturnPreparationByPartner SellerReturnDelivery OgrLogistics "
        "CrossDockHandlingAtDropOff CrossDockDeliveryToAcceptancePoint "
        "CrossDockPartnerHandling"
    ),
    "warehouse": (
        "Placements SupplyInbound TemporaryPlacement TemporaryPlacementsAgent "
        "ReturnStorage B2CTemporaryPlacement MicroFulfillmentSupply"
    ),
    "advertising": (
        "BrandCommission BrandPromotion BrandShelf ExternalPromotion "
        "InternetSiteAdvertising Marketing PayPerClick PremiumCashbackPromotion "
        "SaleReview Stencil SocialMediaAdvertising DisplayAdvertisingPlacement "
        "CustomerReviews AcceleratedReviewCollection FirstCustomerReview PushCampaign"
    ),
    "subscriptions": "PremiumSubscription AnalyticsPlus",
    "penalties": (
        "DefectRate DefectFineModeration DefectFineProhibitedGoods "
        "DefectFineCounterfeitGoods DefectFineComplaint DefectFineErrors "
        "DefectFineShipmentDelayRate"
    ),
    "compensations": (
        "Compensation ItemCompensation ClaimCommission B2CInsuranceCompensation "
        "VolumeObligationReward"
    ),
    "loyalty": (
        "PointsForReviews PremiumCashbackIndividualPoints PremiumMailingCommission "
        "CustomerChatPoints"
    ),
    "adjustments": (
        "SetOff CorrectionCommission BrandDeposit RfbsClientDeliveryCharge RfbsBuyerDelivery"
    ),
}
GROUPS = {
    name.replace("_", " "): group
    for group, names in SERVICE_GROUPS.items()
    for name in names.split()
}
TITLES = {
    "sales": "Продажи и возвраты",
    "fees": "Комиссия и эквайринг",
    "logistics": "Логистика",
    "warehouse": "Хранение и приёмка",
    "advertising": "Реклама",
    "subscriptions": "Подписка",
    "loyalty": "Программа лояльности",
    "penalties": "Штрафы",
    "compensations": "Компенсации",
    "other": "Прочие услуги",
    "adjustments": "Корректировки и взаиморасчёты",
}
INCOME_GROUPS = {"sales", "compensations", "adjustments"}


def line_group(line):
    """Apply current provider categories to saved reports without reimporting their money."""
    return GROUPS.get(line["key"].removeprefix("ozon_"), line["group"])


def amount(value, zero_currency=None):
    if not isinstance(value, dict):
        raise ValueError("money")
    currency = value.get("currency")
    raw = value.get("amount")
    if raw is None or isinstance(raw, bool):
        raise ValueError("amount")
    value = Decimal(str(raw))
    if not value.is_finite() or value.adjusted() > 30:
        raise ValueError("amount")
    if value == 0 and not currency and zero_currency:
        currency = zero_currency
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isupper():
        raise ValueError("currency")
    return value, currency


@money_precision()
def normalize(rows, day, types):
    currencies, seen, realizations, cost_items = {}, {}, [], []
    details = {}

    def bucket(currency, sku):
        return details.setdefault(currency, {}).setdefault(
            sku,
            {
                "lines": {},
                "record_ids": set(),
                "sales": 0,
                "returns": 0,
                "buyer_revenue": Decimal(0),
                "buyer_unknown": False,
            },
        )

    for row in rows:
        rid = row["accrual_id"]
        if not isinstance(rid, int) or isinstance(rid, bool) or rid <= 0:
            raise ValueError("accrual_id")
        if rid in seen:
            if seen[rid] != row:
                raise ValueError("conflicting_accrual")
            continue
        seen[rid] = row
        if date.fromisoformat(row["date"][:10]) != day:
            raise ValueError("wrong_accrual_day")
        total, currency = amount(row["total_amount"])
        target = currencies.setdefault(
            currency,
            {
                "settlement": Decimal(0),
                "seller_revenue": Decimal(0),
                "buyer_revenue": Decimal(0),
                "buyer_unknown": False,
                "lines": {},
            },
        )
        target["settlement"] += total
        accounted = Decimal(0)
        allocation = [""]

        def add(
            group,
            key,
            title,
            value,
            target=target,
            currency=currency,
            allocation=allocation,
            rid=rid,
        ):
            nonlocal accounted
            accounted += value
            line = target["lines"].setdefault((group, key), {"title": title, "amount": Decimal(0)})
            line["amount"] += value
            detail = bucket(currency, allocation[0])
            detail["record_ids"].add(rid)
            target_line = detail["lines"].setdefault(
                (group, key), {"title": title, "amount": Decimal(0)}
            )
            target_line["amount"] += value

        def read(value, currency=currency):
            number, code = amount(value, zero_currency=currency)
            if code != currency:
                raise ValueError("inconsistent_currency")
            return number

        def fee(value):
            tid = value["type_id"]
            source = types.get(tid, {"name": "unknown", "title": "Неизвестное начисление"})
            group = GROUPS.get(source["name"], "other")
            key = "ozon_" + (source["name"] if source["name"] != "unknown" else str(tid))
            add(group, key, source["title"], read(value["accrued"]))

        category = row["accrued_category"]
        if category == "POSTING":
            products = (row.get("posting") or {})["products"]
            for product in products:
                sku_value = product.get("sku")
                allocation[0] = (
                    str(sku_value)
                    if isinstance(sku_value, int)
                    and not isinstance(sku_value, bool)
                    and sku_value > 0
                    else ""
                )
                commission = product.get("commission")
                if commission:
                    sale = read(commission["sale_amount"])
                    target["seller_revenue"] += sale
                    add(
                        "sales",
                        "seller_sales" if sale >= 0 else "seller_returns",
                        "Продажи по цене продавца" if sale >= 0 else "Возвраты по цене продавца",
                        sale,
                    )
                    # Final commission includes discounts and markups. Do not add bonuses again.
                    add(
                        "fees",
                        "ozon_final_commission",
                        "Комиссия за продажу",
                        read(commission["commission"]),
                    )
                    quantity, sku = product.get("quantity"), product.get("sku")
                    valid_quantity = (
                        isinstance(quantity, int)
                        and not isinstance(quantity, bool)
                        and quantity != 0
                    )
                    detail = bucket(currency, allocation[0])
                    if valid_quantity:
                        detail["returns" if sale < 0 else "sales"] += abs(quantity)
                    if sale or valid_quantity:
                        cost_items.append(
                            {
                                "key": row.get("unit_number") or "",
                                "sku": str(sku or ""),
                                "quantity": abs(quantity) * (-1 if sale < 0 else 1)
                                if valid_quantity
                                else None,
                                "currency": currency,
                            }
                        )
                    if (
                        isinstance(quantity, int)
                        and not isinstance(quantity, bool)
                        and quantity != 0
                        and commission.get("sale_price")
                    ):
                        price = read(commission["sale_price"])
                        if price < 0 and sale >= 0:
                            raise ValueError("negative_customer_price")
                        price, quantity = abs(price), abs(quantity)
                        target["buyer_revenue"] += price * quantity * (-1 if sale < 0 else 1)
                        detail["buyer_revenue"] += price * quantity * (-1 if sale < 0 else 1)
                        if sale > 0 and isinstance(sku, int) and sku > 0 and row.get("unit_number"):
                            realizations.append(
                                {
                                    "number": row["unit_number"],
                                    "sku": str(sku),
                                    "price": money(price),
                                    "currency": currency,
                                }
                            )
                    elif sale:
                        target["buyer_unknown"] = True
                        detail["buyer_unknown"] = True
                delivery = product.get("delivery")
                if delivery:
                    before = accounted
                    for service in delivery.get("services", []):
                        fee(service)
                    residual = read(delivery["total_accrued"]) - (accounted - before)
                    if residual:
                        add(
                            "logistics",
                            "ozon_delivery_residual",
                            "Прочая доставка",
                            residual,
                        )
        elif category == "ITEM":
            for item in (row.get("item_fees") or {})["fees"]:
                sku_value = item.get("sku")
                allocation[0] = (
                    str(sku_value)
                    if isinstance(sku_value, int)
                    and not isinstance(sku_value, bool)
                    and sku_value > 0
                    else ""
                )
                for value in item["fees"]:
                    fee(value)
        elif category == "NON_ITEM":
            fee(row["non_item_fee"])
        elif category == "CONTAINER_FEES":
            for value in (row.get("container_fees") or {})["fees"]:
                fee(value)
        allocation[0] = ""
        # New/unknown categories and provider differences remain visible and reconcile to total.
        if total != accounted:
            add("other", "ozon_unreconciled", "Прочие начисления", total - accounted)
    return {
        "details_basis": "accrual_products_v1",
        "product_details": {
            currency: {
                sku: {
                    "records": len(value["record_ids"]),
                    "sales": value["sales"],
                    "returns": value["returns"],
                    "buyer_revenue": None
                    if value["buyer_unknown"]
                    else money(value["buyer_revenue"]),
                    "lines": [
                        {
                            "group": group,
                            "key": key,
                            "title": line["title"],
                            "amount": money(line["amount"]),
                        }
                        for (group, key), line in sorted(value["lines"].items())
                    ],
                }
                for sku, value in products.items()
            }
            for currency, products in details.items()
        },
        "records": len(seen),
        "cost_basis": "accrual_v1",
        "cost_items": cost_items,
        "realizations": realizations,
        "currencies": {
            currency: {
                "seller_revenue": money(value["seller_revenue"]),
                "buyer_revenue": None if value["buyer_unknown"] else money(value["buyer_revenue"]),
                "settlement": money(value["settlement"]),
                "lines": [
                    {
                        "group": group,
                        "key": key,
                        "title": line["title"],
                        "amount": money(line["amount"]),
                    }
                    for (group, key), line in sorted(value["lines"].items())
                ],
            }
            for currency, value in currencies.items()
        },
    }


def normalize_partial(rows, day, types):
    """Isolate malformed rows; known amounts are never presented as a complete day."""
    good, issues = [], []
    for index, row in enumerate(rows):
        try:
            normalize([row], day, types)
            good.append(row)
        except ValueError, KeyError, TypeError, ArithmeticError:
            issues.append(
                {
                    "record_id": str(
                        row.get("accrual_id", index) if isinstance(row, dict) else index
                    )[:128],
                    "reason": "ozon_invalid_record",
                }
            )
    result = normalize(good, day, types)
    result["issues"] = issues
    result["is_partial"] = bool(issues)
    return result
