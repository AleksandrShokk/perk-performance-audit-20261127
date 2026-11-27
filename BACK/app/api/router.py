from fastapi import APIRouter, Depends

from app.api.health import router as health_router
from app.modules.accounts.access import authorize_workspace
from app.modules.accounts.ozon_router import router as ozon_router
from app.modules.accounts.router import router as accounts_router
from app.modules.accounts.team import router as team_router
from app.modules.auth.router import router as auth_router
from app.modules.catalog.import_router import router as catalog_import_router
from app.modules.catalog.router import router as catalog_router
from app.modules.finance.economics_router import router as economics_router
from app.modules.finance.export import router as finance_export_router
from app.modules.finance.router import router as finance_router
from app.modules.finance.variant_costs import router as variant_costs_router
from app.modules.insights.business import router as business_router
from app.modules.insights.export_router import router as analytics_export_router
from app.modules.insights.router import router as insights_router
from app.modules.inventory.export import router as inventory_export_router
from app.modules.inventory.overview_router import router as inventory_overview_router
from app.modules.inventory.router import router as inventory_router
from app.modules.inventory.settings import router as inventory_settings_router
from app.modules.notifications.router import router as notifications_router
from app.modules.notifications.router import webhook_router as telegram_webhook_router
from app.modules.supplies.destinations.router import (
    router as supply_destinations_router,
)
from app.modules.supplies.packaging import router as packaging_router
from app.modules.supplies.plan_router import router as supply_plan_router
from app.modules.supplies.router import router as supply_router
from app.modules.supplies.template_router import router as supply_template_router
from app.modules.sync.router import router as sync_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(accounts_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(ozon_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(team_router)
api_router.include_router(sync_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(finance_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(variant_costs_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(inventory_settings_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(catalog_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(economics_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(inventory_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(inventory_overview_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(supply_destinations_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(supply_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(supply_template_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(supply_plan_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(packaging_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(insights_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(business_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(notifications_router)
api_router.include_router(telegram_webhook_router)

api_router.include_router(catalog_import_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(analytics_export_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(finance_export_router, dependencies=[Depends(authorize_workspace)])
api_router.include_router(inventory_export_router, dependencies=[Depends(authorize_workspace)])
