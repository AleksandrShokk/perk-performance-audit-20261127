"""One permission catalogue and a fail-closed guard for every workspace API route."""

from uuid import UUID

from fastapi import HTTPException, Request

from app.modules.auth.dependencies import DB, FullIdentity
from app.modules.auth.models import Membership

PERMISSIONS = {
    "analytics.read": "Аналитика",
    "inventory.read": "Товары и остатки",
    "finance.read": "Финансы",
    "profit.read": "Себестоимость и прибыль",
    "costs.write": "Изменение себестоимости",
    "expenses.write": "Изменение расходов",
    "taxes.write": "Налоговые настройки",
    "reports.export": "Экспорт отчётов",
}
FULL_ROLES = {"owner", "admin"}
ROLE_DEFAULTS = {
    "manager": ["analytics.read", "inventory.read"],
    "accountant": [
        "analytics.read",
        "finance.read",
        "profit.read",
        "costs.write",
        "expenses.write",
        "taxes.write",
        "reports.export",
    ],
    # Preserve the existing viewer's read-only access when permissions are unspecified.
    "viewer": ["analytics.read", "inventory.read", "finance.read", "profit.read"],
}


def normalize_permissions(values):
    permissions = set(values)
    if permissions & {"profit.read", "expenses.write", "taxes.write", "costs.write"}:
        permissions.add("finance.read")
    if permissions & {"costs.write", "taxes.write"}:
        permissions.add("profit.read")
    return sorted(permissions)


def effective(member):
    if member.role in FULL_ROLES:
        return list(PERMISSIONS)
    return normalize_permissions(
        member.permissions if member.permissions is not None else ROLE_DEFAULTS.get(member.role, [])
    )


def allows(member, permission):
    return permission in effective(member)


def member_for(db, user_id, workspace_id):
    member = db.get(Membership, (user_id, workspace_id))
    if member is None:
        raise HTTPException(404, "Кабинет не найден.")
    return member


def require_permission(db, identity, workspace_id, permission):
    member = member_for(db, identity.user.id, workspace_id)
    if not allows(member, permission):
        raise HTTPException(
            403,
            {"code": "permission_denied", "message": "Нет доступа к этому действию."},
        )
    return member


def store_allowed(member, store_id):
    return (
        member.role in FULL_ROLES or member.store_ids is None or str(store_id) in member.store_ids
    )


READ_RULES = {
    "inventoryPackagingTemplate": (),
    "inventoryPackagingPreview": (),
    "inventoryPackagingApply": (),
    "catalogMatchesList": (),
    "catalogMatchesTemplate": (),
    "catalogMatchesPreview": (),
    "catalogMatchesAutomatic": (),
    "catalogMatchesApply": (),
    "catalogMatchDelete": (),
    "supplyTemplateBlank": ("inventory.read", "reports.export"),
    "analyticsSalesExport": ("analytics.read", "reports.export"),
    "financeOverviewExport": ("finance.read", "reports.export"),
    "inventoryOverviewExport": ("inventory.read", "reports.export"),
    "storesList": (),
    "storeImportedData": (),
    "storeConnectionStatus": (),
    "storeSyncHistory": (),
    "storeSyncSchedule": (),
    "storeSyncCapabilities": (),
    "storeSyncStatus": (),
    "businessReport": (),
    "financeOverview": ("finance.read",),
    "financeSummary": ("finance.read",),
    "financeBalance": ("finance.read",),
    "financeABC": ("finance.read",),
    "financeNetProfit": ("profit.read",),
    "financeUnitEconomics": ("profit.read",),
    "financeSimulatePrice": ("profit.read",),
    "catalogModels": (),
    "catalogProducts": (),  # The route allows inventory OR cost access, with separate redaction.
    "costsList": ("profit.read",),
    "costsCalculate": ("profit.read",),
    "taxSettingsList": ("profit.read",),
    "expensesList": ("finance.read",),
    "expensesTotals": ("finance.read",),
    "inventoryForecast": ("inventory.read",),
    "inventorySettingsGet": ("inventory.read",),
    "variantCostsList": ("profit.read",),
    "inventorySupplyPlan": ("inventory.read",),
    "inventoryHistory": ("inventory.read",),
    "inventoryOverview": ("inventory.read",),
    "inventoryDestinations": ("inventory.read",),
    "inventoryDestinationsRefresh": ("inventory.read",),
    "inventoryReplenishment": ("inventory.read",),
    "inventoryReplenishmentExport": ("inventory.read", "reports.export"),
    "inventorySupplies": ("inventory.read",),
    "supplyPlansList": ("inventory.read",),
    "supplyPlanGet": ("inventory.read",),
    "supplyPlanExport": ("inventory.read", "reports.export"),
    "supplyPlanItemsExport": ("inventory.read", "reports.export"),
    "supplyTemplateInspect": (
        "inventory.read",
        "reports.export",
    ),  # Read-only multipart POST.
    "supplyTemplateFill": ("inventory.read", "reports.export"),
    "insightsFunnel": ("analytics.read",),
    "insightsFunnelAvailability": ("analytics.read",),
    "insightsFunnelProgress": ("analytics.read",),
    "insightsFunnelSummary": ("analytics.read",),
    "insightsOrders": ("analytics.read",),
    "insightsBuyouts": ("analytics.read",),
    "insightsReturns": ("analytics.read",),
    "insightsSeasonality": ("analytics.read",),
    "storeEventsList": ("analytics.read",),
    # These combined legacy reports contain financial and operational data.
    "storeDashboard": (
        "analytics.read",
        "inventory.read",
        "finance.read",
        "profit.read",
    ),
    "insightsMoneyAudit": ("finance.read", "profit.read", "inventory.read"),
    "storeAnalytics": (
        "analytics.read",
        "inventory.read",
        "finance.read",
        "profit.read",
    ),
    "storeGoalProgress": ("analytics.read", "finance.read", "profit.read"),
}
WRITE_RULES = {
    "supplyPlanCreate": ("inventory.read",),  # Owner/admin in the route.
    "supplyPlanSave": ("inventory.read",),
    "supplyPlanVariantsLoad": ("inventory.read",),
    "inventoryPackagingSave": ("inventory.read",),  # Owner/admin only in the route.
    "storeRename": (),  # The route additionally requires owner/admin.
    "inventorySettingsSave": ("inventory.read",),
    "variantCostsSave": ("costs.write",),
    "catalogGroupSave": (),  # The route requires owner/admin, including for direct calls.
    "costsSave": ("costs.write",),
    "costsDownloadTemplate": ("costs.write",),
    "costsPreviewImport": ("costs.write",),
    "costsApplyImport": ("costs.write",),
    "expensesCreate": ("expenses.write",),
    "expensesDelete": ("expenses.write",),
    "taxSettingsSave": ("taxes.write",),
    "taxSettingsDelete": ("taxes.write",),
}


def authorize_workspace(request: Request, db: DB, identity: FullIdentity):
    value = request.path_params.get("workspace_id")
    if value is None:
        return
    try:
        workspace_id = UUID(str(value))
    except ValueError:
        raise HTTPException(422, "Некорректный кабинет") from None
    member = member_for(db, identity.user.id, workspace_id)
    store_id = request.path_params.get("store_id") or request.query_params.get("store_id")
    if store_id and not store_allowed(member, store_id):
        raise HTTPException(404, "Магазин не найден.")
    operation = request.scope["route"].operation_id
    if member.role in FULL_ROLES:
        return
    required = READ_RULES.get(operation, WRITE_RULES.get(operation))
    if required is None:
        # New routes are unavailable to employees until deliberately classified.
        raise HTTPException(404, "Кабинет не найден.")
    if any(not allows(member, permission) for permission in required):
        raise HTTPException(
            403,
            {"code": "permission_denied", "message": "Нет доступа к этому разделу."},
        )
    if operation == "storeImportedData":
        permission = {
            "catalog": "inventory.read",
            "stocks": "inventory.read",
            "fbs": "inventory.read",
            "prices": "inventory.read",
            "stock_history": "inventory.read",
            "supply_demand": "inventory.read",
            "fbs_demand": "inventory.read",
            "supplies": "inventory.read",
            "sales": "analytics.read",
            "orders": "analytics.read",
            "funnel": "analytics.read",
            "returns": "analytics.read",
            "finance": "finance.read",
            "balance": "finance.read",
        }.get(request.path_params.get("source"))
        if permission is None or not allows(member, permission):
            raise HTTPException(
                403, {"code": "permission_denied", "message": "Нет доступа к данным."}
            )
    if operation == "businessReport":
        topic = request.query_params.get("topic", "overview")
        permission = {
            "sales": "finance.read",
            "profit": "profit.read",
            "finance": "finance.read",
            "stock": "inventory.read",
            "orders": "analytics.read",
            "buyouts": "analytics.read",
            "funnel": "analytics.read",
        }.get(topic)
        if permission and not allows(member, permission):
            raise HTTPException(
                403,
                {"code": "permission_denied", "message": "Нет доступа к этому отчёту."},
            )
    if (
        operation == "financeABC"
        and request.query_params.get("metric") == "contribution"
        and not allows(member, "profit.read")
    ):
        raise HTTPException(403, {"code": "permission_denied", "message": "Нет доступа к прибыли."})


def hide_profit(report):
    """Never modify the shared cached report. Remove all values that reveal product cost."""
    result = report.model_copy(deep=True)
    for row in [result.summary, result.unassigned, *result.daily, *result.products]:
        for field in [
            "cogs",
            "profit_before_tax",
            "contribution_before_external_expenses",
            "margin_percent",
        ]:
            setattr(row, field, None)
        row.calculation_complete = False
        row.financial_details = {
            key: value
            for key, value in row.financial_details.items()
            if key
            not in {
                "cogs",
                "total_expenses",
                "profit_before_tax",
                "margin_percent",
                "net_profit",
                "missing_cost_skus",
            }
        }
    return result
