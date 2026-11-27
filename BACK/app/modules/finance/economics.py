"""Per-unit economics, taxes and price simulation over the published profit report.

Pure functions on report values: no new accounting rules. Unknown inputs stay unknown.
Tax figures are estimates for planning, not a tax return: annual rules, insurance
contribution deductions and special cases are out of scope and stated in the response.
"""

from decimal import Decimal

from app.modules.finance.precision import money

CENT = Decimal("0.01")
PRICE_DRIVEN = ("delivery_service", "paid_storage", "paid_acceptance")
PENALTIES = ("penalty", "deduction")
USN_MINIMUM_RATE = Decimal(1)


def dec(value):
    return None if value is None else Decimal(value)


def per_unit(value, units):
    return None if value is None or units <= 0 else value / units


def vat_inside(amount, vat_rate):
    """VAT included in a gross amount."""
    return amount * vat_rate / (100 + vat_rate) if vat_rate else Decimal(0)


def tax_estimate(setting, *, revenue, payout, profit, income_adjustment=Decimal(0)):
    """Signed non-sale income adjusts income tax, not sales VAT or profit a second time."""
    if setting is None or setting.regime == "none":
        return Decimal(0), Decimal(0), []
    gross = revenue if setting.income_base == "revenue" else payout
    if gross is None:
        return None, None, ["Не хватает выручки для расчёта налога."]
    vat = vat_inside(gross, setting.vat_rate)
    if income_adjustment is None:
        return vat, None, ["Не хватает данных о компенсациях для расчёта налога."]
    income = gross - vat + income_adjustment
    rate = setting.rate / 100
    notes = []
    if setting.regime == "usn_income":
        tax = income * rate
        notes.append("УСН «доходы»: без уменьшения на страховые взносы.")
    else:
        if profit is None:
            return vat, None, ["Не хватает данных о прибыли для расчёта налога."]
        base = profit - vat
        tax = max(Decimal(0), base) * rate
        if setting.regime == "usn_income_expense":
            minimum = income * USN_MINIMUM_RATE / 100
            if tax < minimum:
                tax = minimum
                notes.append("Применён минимальный налог 1% от доходов (правило считается за год).")
            notes.append("УСН «доходы минус расходы»: оценка за период, налог считается за год.")
        else:
            notes.append("Налог на прибыль: оценка за период без переносимых убытков.")
    if vat:
        notes.append(f"НДС {setting.vat_rate}% выделен из суммы, входящей в налоговую базу.")
    return vat, tax, notes


def net_profit(setting, values):
    revenue, payout, profit = (
        dec(values.revenue),
        dec(values.for_pay),
        dec(values.profit_before_tax),
    )
    vat, tax, notes = tax_estimate(
        setting,
        revenue=revenue,
        payout=payout,
        profit=profit,
        income_adjustment=dec(values.financial_details.get("tax_income_adjustment", "0")),
    )
    net = None if profit is None or vat is None or tax is None else profit - vat - tax
    return {
        "profit_before_tax": money(profit),
        "vat": money(vat),
        "tax": money(tax),
        "net_profit": money(net),
        "net_margin_percent": format((net / revenue * 100).quantize(CENT), "f")
        if net is not None and revenue
        else None,
        "notes": notes,
    }


def classify(contribution, revenue, target):
    if contribution is None or revenue is None or revenue <= 0:
        return "unknown"
    if contribution < 0:
        return "loss"
    if contribution / revenue * 100 < target:
        return "marginal"
    return "profitable"


def unit_row(product, setting, margin_target):
    units = product.net_units
    revenue = dec(product.revenue)
    payout = dec(product.for_pay)
    expenses = {field: dec(product.wb_expenses.get(field)) for field in PRICE_DRIVEN + PENALTIES}
    cogs = dec(product.cogs)
    contribution = dec(product.contribution_before_external_expenses)
    vat, tax, _ = tax_estimate(
        setting,
        revenue=revenue,
        payout=payout,
        profit=contribution,
        income_adjustment=dec(product.financial_details.get("tax_income_adjustment", "0")),
    )
    after_tax = (
        None if contribution is None or vat is None or tax is None else contribution - vat - tax
    )
    marketplace_fee = None if revenue is None or payout is None else revenue - payout
    if getattr(product, "marketplace", None) == "ozon":
        marketplace_fee = dec(product.financial_details.get("fees_total"))
    penalties = (
        None
        if any(expenses[field] is None for field in PENALTIES)
        else sum((expenses[field] for field in PENALTIES), Decimal(0))
    )
    return {
        "nm_id": product.nm_id,
        "net_units": units,
        "sales": product.sales,
        "returns": product.returns,
        "price": money(per_unit(revenue, units)),
        "marketplace_fee": money(per_unit(marketplace_fee, units)),
        "logistics": money(per_unit(expenses["delivery_service"], units)),
        "storage": money(per_unit(expenses["paid_storage"], units)),
        "acceptance": money(per_unit(expenses["paid_acceptance"], units)),
        "penalties": money(per_unit(penalties, units)),
        "cost_price": money(per_unit(cogs, units)),
        "tax": money(per_unit(None if tax is None or vat is None else tax + vat, units)),
        "profit": money(per_unit(after_tax, units)),
        "margin_percent": format((after_tax / revenue * 100).quantize(CENT), "f")
        if after_tax is not None and revenue
        else None,
        "total_profit": money(after_tax),
        "status": classify(after_tax, revenue, margin_target),
        "issues": product.issues,
    }


def simulate(product, setting, *, price, cost_price, units_expected=None):
    """Price scenario from this SKU's history: payout share and per-unit WB costs stay as observed.

    Profit(p) = p·share − VAT(p) − tax(p) − fixed is linear, so break-even is exact.
    """
    units = product.net_units
    revenue, payout = dec(product.revenue), dec(product.for_pay)
    if units <= 0 or not revenue or payout is None:
        return None
    share = payout / revenue
    costs = {field: dec(product.wb_expenses.get(field)) for field in PRICE_DRIVEN}
    if any(value is None for value in costs.values()):
        return None
    fixed_wb = sum(costs.values(), Decimal(0)) / units
    fixed = fixed_wb + cost_price
    vat_rate = setting.vat_rate if setting else Decimal(0)
    rate = setting.rate / 100 if setting and setting.regime != "none" else Decimal(0)
    on_revenue = bool(setting and setting.regime == "usn_income")
    base_share = share if setting and setting.income_base == "payout" else Decimal(1)

    def profit_at(p):
        gross = p * base_share
        vat = vat_inside(gross, vat_rate)
        before_tax = p * share - vat - fixed
        tax = (gross - vat) * rate if on_revenue else max(Decimal(0), before_tax) * rate
        return before_tax - tax, vat + tax

    profit, taxes = profit_at(price)
    vat_part = base_share * vat_rate / (100 + vat_rate) if vat_rate else Decimal(0)
    slope = share - vat_part - (base_share * 100 / (100 + vat_rate) * rate if on_revenue else 0)
    break_even = fixed / slope if slope > 0 else None
    current = dec(product.contribution_before_external_expenses)
    result = {
        "nm_id": product.nm_id,
        "price": money(price),
        "payout_share_percent": format((share * 100).quantize(CENT), "f"),
        "payout": money(price * share),
        "wb_costs_per_unit": money(fixed_wb),
        "cost_price": money(cost_price),
        "taxes": money(taxes),
        "profit_per_unit": money(profit),
        "margin_percent": format((profit / price * 100).quantize(CENT), "f") if price else None,
        "break_even_price": money(break_even),
        "history_units": units,
        "history_price": money(revenue / units),
        "units_to_match_history_profit": None,
        "expected_profit": money(profit * units_expected) if units_expected else None,
    }
    if current is not None and current > 0 and profit > 0:
        result["units_to_match_history_profit"] = int(
            (current / profit).to_integral_value(rounding="ROUND_CEILING")
        )
    return result
