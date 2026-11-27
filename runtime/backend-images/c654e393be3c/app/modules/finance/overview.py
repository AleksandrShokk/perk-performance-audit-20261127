"""Reader-facing finance groups over the existing exact-money profit report."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.finance import economics
from app.modules.finance.precision import money_precision


class FinanceLine(BaseModel):
    key: str
    title: str
    amount: str | None
    unit: Literal["money", "units", "percent"] = "money"
    note: str | None = None


class FinanceGroup(BaseModel):
    key: str
    title: str
    amount: str | None
    share_percent: str | None
    note: str | None = None
    lines: list[FinanceLine]


class FinanceTotals(BaseModel):
    storage_total: str | None = None
    seller_revenue: str | None
    marketplace_revenue: str | None
    expenses_before_tax: str | None
    profit_before_tax: str | None
    settlement: str | None


class FinanceTaxes(BaseModel):
    configured_stores: int
    total_stores: int
    vat: str | None
    tax: str | None
    net_profit: str | None
    notes: list[str]


class FinanceOverview(BaseModel):
    data_sources: list[str] = Field(default_factory=lambda: ["wb_finance"])
    known_days: int | None = None
    source_errors: list[str] = Field(default_factory=list)
    date_from: date
    date_to: date
    currency: str
    updated_at: datetime | None
    is_partial: bool
    is_loading: bool
    period_covered: bool
    expenses_exclude_cogs: bool
    total_stores: int
    totals: FinanceTotals
    groups: list[FinanceGroup]
    taxes: FinanceTaxes
    notes: list[str] = Field(default_factory=list)


def add(*amounts):
    return (
        None
        if any(value is None for value in amounts)
        else format(sum((Decimal(value) for value in amounts), Decimal(0)), "f")
    )


def percent(amount, revenue):
    if amount is None or revenue is None or Decimal(revenue) <= 0:
        return None
    return format((Decimal(amount) / Decimal(revenue) * 100).quantize(Decimal("0.1")), "f")


def negative(amount):
    return None if amount is None else format(-Decimal(amount), "f")


def line(key, title, amount, note=None, unit="money"):
    return FinanceLine(key=key, title=title, amount=amount, note=note, unit=unit)


@money_precision()
def build_groups(summary):
    details, expenses = summary.financial_details, summary.wb_expenses
    get = details.get
    revenue = get("seller_revenue")
    groups = []

    def group(key, title, amount, lines, note=None):
        groups.append(
            FinanceGroup(
                key=key,
                title=title,
                amount=amount,
                share_percent=percent(amount, revenue),
                lines=lines,
                note=note,
            )
        )

    group(
        "sales",
        "Продажи и возвраты",
        revenue,
        [
            line("seller_sales", "Продажи по цене продавца", get("seller_sales")),
            line("seller_returns", "Возвраты по цене продавца", negative(get("seller_returns"))),
            line(
                "marketplace_revenue",
                "WB реализовал",
                summary.revenue,
                "Цена реализации WB. Может отличаться от цены продавца из-за скидок площадки.",
            ),
            line(
                "units",
                "Продано за вычетом возвратов",
                str(summary.net_units) if summary.records else None,
                unit="units",
            ),
        ],
        "Финансовые операции по дате отчёта. Аналитика заказов и выкупов находится в воронке.",
    )
    group(
        "fees",
        "Комиссия и эквайринг",
        get("fees_total"),
        [
            line("commission", "Комиссия WB", get("commission")),
            line("acquiring", "Эквайринг с корректировками", get("acquiring")),
            line(
                "acquiring_corrections",
                "Возврат эквайринга (учтён)",
                get("acquiring_corrections"),
                "Уже уменьшает сумму эквайринга выше.",
            ),
        ],
        "Уже учтены в перечислении за товар; повторно из прибыли не вычитаются.",
    )
    group(
        "logistics",
        "Логистика",
        expenses.get("delivery_service"),
        [
            line("forward", "К покупателю", get("logistics_forward")),
            line("reverse", "От покупателя", get("logistics_reverse")),
            line("other", "Другие операции доставки", get("logistics_other")),
        ],
    )
    group(
        "warehouse",
        "Хранение и приёмка",
        add(expenses.get("paid_storage"), expenses.get("paid_acceptance")),
        [
            line("storage", "Хранение", expenses.get("paid_storage")),
            line("acceptance", "Приёмка и обработка", expenses.get("paid_acceptance")),
        ],
    )
    advertising = get("deduction_advertising")
    external_advertising = get("external_advertising")
    group(
        "advertising",
        "Реклама",
        add(advertising, external_advertising),
        [
            line("wb", "WB Продвижение", advertising),
            line("external", "Внешняя реклама", external_advertising),
        ],
    )
    group(
        "services",
        "Сервисы WB",
        add(expenses.get("deduction"), expenses.get("payment_schedule"), negative(advertising)),
        [
            line("jam", "Подписка «Джем»", get("deduction_jam")),
            line("showcase", "Витрина магазина", get("deduction_showcase")),
            line(
                "payout",
                "Изменение срока выплат",
                add(get("deduction_payout_service"), expenses.get("payment_schedule")),
            ),
            line("other", "Прочие удержания", get("deduction_other")),
        ],
        "Расшифровка общей суммы удержаний. Категории не прибавляются к ней повторно.",
    )
    group(
        "penalties",
        "Штрафы",
        expenses.get("penalty"),
        [
            line("penalties", "Штрафы WB", expenses.get("penalty")),
        ],
    )
    group(
        "compensations",
        "Компенсации WB",
        get("compensations_total"),
        [
            line("defect", "Брак и добровольная компенсация", get("compensation_defect")),
            line("damage", "Потеря, подмена и ущерб", get("compensation_damage")),
        ],
        "Поступления, уже учтённые в расчёте перечисления. Отделены от расходов.",
    )
    group(
        "loyalty",
        "Программа лояльности",
        add(get("loyalty_points"), get("loyalty_cost")),
        [
            line("points", "Удержанные баллы", get("loyalty_points")),
            line("cost", "Стоимость участия", get("loyalty_cost")),
            line(
                "compensation",
                "Компенсация скидки (учтена)",
                get("loyalty_compensation"),
                "Отдельная сумма WB; не прибавляется к перечислению повторно.",
            ),
        ],
        "Баллы и комиссия уменьшают перечисление. Компенсация скидки уже входит в продажу.",
    )
    group(
        "adjustments",
        "Корректировки WB",
        expenses.get("additional_payment"),
        [
            line(
                "additional_payment",
                "Корректировка вознаграждения",
                expenses.get("additional_payment"),
            ),
        ],
        "Положительная сумма — удержание, отрицательная — возврат продавцу.",
    )
    group(
        "cogs",
        "Себестоимость",
        summary.cogs if summary.records else None,
        [
            line("cogs", "Товары за вычетом возвратов", summary.cogs if summary.records else None),
            line(
                "missing_skus",
                "Варианты без себестоимости",
                get("missing_cost_skus"),
                unit="units",
            ),
            line(
                "missing_units",
                "Продажи и возвраты без цены",
                str(summary.issues.get("missing_cost_units", 0)),
                unit="units",
            ),
        ],
        "Ваши цены. Возврат восстанавливает стоимость исходной продажи, когда она известна.",
    )
    external_labels = {
        "packaging": "Упаковка",
        "fulfillment": "Фулфилмент",
        "transport": "Доставка вне WB",
        "rent": "Аренда",
        "salary": "Оплата труда",
        "other": "Прочие расходы",
    }
    group(
        "external",
        "Внешние расходы",
        add(summary.external_expenses, negative(external_advertising)) if summary.records else None,
        [line(key, title, get("external_" + key)) for key, title in external_labels.items()],
        "Введённые вами расходы, которые не входят в отчёт WB.",
    )
    return groups


@money_precision()
def taxes_for_stores(stores, settings):
    rows, notes = [], []
    configured = 0
    for store, (setting, changed) in zip(stores, settings, strict=True):
        if setting is None:
            notes.append("Выберите налоговые настройки для расчёта чистой прибыли.")
            rows.append({"vat": None, "tax": None, "net_profit": None})
            continue
        configured += 1
        if changed:
            notes.append(
                "Внутри периода менялись налоговые настройки. Выберите период с одним режимом."
            )
            rows.append({"vat": None, "tax": None, "net_profit": None})
            continue
        value = economics.net_profit(setting, store.finance.summary)
        notes.extend(value["notes"])
        if not store.finance.summary.calculation_complete:
            value["net_profit"] = None
        rows.append(value)
    notes.insert(
        0,
        "Оценка за выбранный период. НДС к вычету и годовые корректировки здесь не рассчитываются.",
    )
    return FinanceTaxes(
        configured_stores=configured,
        total_stores=len(stores),
        notes=list(dict.fromkeys(notes)),
        **{
            field: add(*(row[field] for row in rows)) if rows else None
            for field in ("vat", "tax", "net_profit")
        },
    )


@money_precision()
def build_overview(business, settings):
    report, summary = business.finance, business.finance.summary
    details = summary.financial_details
    expenses = details.get("total_expenses")
    excludes_cogs = summary.cogs is None
    if expenses is None and excludes_cogs:
        expenses = add(details.get("wb_expenses_total"), summary.external_expenses)
    notes = []
    if not report.period_covered or report.is_partial:
        notes.append("Период ещё загружен не полностью. Доступные суммы предварительные.")
    if Decimal(details.get("unclassified_deduction_rows") or "0"):
        notes.append("Для части удержаний нет описания услуги. Они находятся в прочих удержаниях.")
    if any(
        summary.issues.get("missing_" + field)
        for field in (
            "payment_schedule",
            "additional_payment",
            "cashback_amount",
            "cashback_commission_change",
        )
    ):
        notes.append("Обновляем финансовую расшифровку WB. Расчёт пока неполный.")
    if summary.issues.get("missing_cost_units"):
        notes.append("Добавьте себестоимость товаров, чтобы подтвердить прибыль.")
    if summary.issues.get("unclassified_operation") or summary.issues.get(
        "unreconciled_adjustment"
    ):
        notes.append(
            "Есть операции WB, требующие сверки. Прибыль появится после подтверждения расчёта."
        )
    return FinanceOverview(
        date_from=report.date_from,
        date_to=report.date_to,
        currency=report.currency,
        updated_at=min(
            (store.finance.updated_at for store in business.stores if store.finance.updated_at),
            default=None,
        ),
        is_partial=report.is_partial,
        is_loading=any(
            store.finance.status == "preparing" or store.finance.is_partial
            for store in business.stores
        ),
        period_covered=report.period_covered,
        expenses_exclude_cogs=excludes_cogs,
        total_stores=business.total_stores,
        totals=FinanceTotals(
            storage_total=summary.wb_expenses.get("paid_storage"),
            seller_revenue=details.get("seller_revenue"),
            marketplace_revenue=summary.revenue,
            expenses_before_tax=expenses,
            profit_before_tax=summary.profit_before_tax if summary.calculation_complete else None,
            settlement=summary.settlement_estimate,
        ),
        groups=build_groups(summary),
        taxes=taxes_for_stores(business.stores, settings),
        notes=notes,
    )


def custom_expense_lines(result, db, vault, wid, stores):
    """Name user-defined expense lines without counting them again in the totals."""
    from collections import defaultdict
    from hashlib import sha256

    from sqlalchemy import select

    from app.modules.finance.models import ExternalExpense
    from app.modules.finance.service import expense_view

    rows = db.scalars(
        select(ExternalExpense)
        .where(
            ExternalExpense.workspace_id == wid,
            ExternalExpense.store_id.in_(stores),
            ExternalExpense.deleted_at.is_(None),
            ExternalExpense.currency == result.currency,
            ExternalExpense.expense_date.between(result.date_from, result.date_to),
        )
        .limit(10001)
    ).all()
    if len(rows) > 10000:
        from fastapi import HTTPException

        raise HTTPException(422, "Слишком много расходов. Уточните период.")
    grouped = defaultdict(Decimal)
    for row in rows:
        value = expense_view(vault, row)
        if value.custom_category and value.category == "other":
            grouped[value.custom_category] += Decimal(value.amount)
    target = next((g for g in result.groups if g.key == "external"), None)
    if target and grouped:
        # Mixed reports can contain already-named lines from a child report.
        previous = sum(
            (
                Decimal(item.amount)
                for item in target.lines
                if item.key.startswith("custom_") and item.amount is not None
            ),
            Decimal(0),
        )
        target.lines = [item for item in target.lines if not item.key.startswith("custom_")]
        other = next((item for item in target.lines if item.key == "other"), None)
        if other and other.amount is not None:
            other.amount = format(Decimal(other.amount) + previous - sum(grouped.values()), "f")
        target.lines.extend(
            line("custom_" + sha256(title.encode()).hexdigest()[:16], title, format(amount, "f"))
            for title, amount in sorted(grouped.items())
        )
    return result
