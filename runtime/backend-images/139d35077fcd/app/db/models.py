"""Import every model here so Alembic sees all tables."""

from app.modules.accounts.models import (
    Store,
    StoreCredential,
    Workspace,
    WorkspaceInvite,
)
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import (
    AccessToken,
    AuthSession,
    Membership,
    OtpChallenge,
    RecoveryCode,
    RefreshToken,
    User,
)
from app.modules.catalog.marketplace_models import (
    MarketplaceCatalogSnapshot,
    OzonCatalogSync,
)
from app.modules.catalog.match_models import CatalogImportPreview, ProductMatch
from app.modules.catalog.models import CatalogOverride
from app.modules.finance.marketplace_models import (
    MarketplaceFinanceDay,
    MarketplaceRealization,
    MarketplaceVariantCost,
)
from app.modules.finance.models import (
    CostImport,
    ExternalExpense,
    FinanceDay,
    FinanceProjection,
    ProductCost,
    TaxSetting,
)
from app.modules.insights.extra_models import (
    MarketplaceSupplySnapshot,
    MarketplaceTrafficDay,
)
from app.modules.insights.marketplace_models import (
    MarketplaceSalesDay,
    MarketplaceStockCover,
    OzonAnalyticsSync,
)
from app.modules.insights.models import InsightSnapshot, StoreEvent, StoreGoal
from app.modules.inventory.models import InventorySnapshot
from app.modules.inventory.settings_models import InventorySettings
from app.modules.notifications.models import (
    Notification,
    NotificationSettings,
    PushDevice,
)
from app.modules.supplies.destinations.models import (
    SupplyDestinationSnapshot,
    SupplyDestinationSync,
)
from app.modules.supplies.models import SupplyPackaging, SupplyPlan
from app.modules.sync.issues import ImportIssue
from app.modules.sync.models import (
    SyncRun,
    SyncSchedule,
    WBDailyMetric,
    WBMetricVersion,
    WBRecord,
    WBStagedRecord,
)

__all__ = [
    "ImportIssue",
    "AccessToken",
    "AuditEvent",
    "AuthSession",
    "CatalogImportPreview",
    "CatalogOverride",
    "CostImport",
    "ExternalExpense",
    "FinanceDay",
    "FinanceProjection",
    "InsightSnapshot",
    "InventorySettings",
    "InventorySnapshot",
    "MarketplaceCatalogSnapshot",
    "MarketplaceFinanceDay",
    "MarketplaceRealization",
    "MarketplaceSalesDay",
    "MarketplaceStockCover",
    "MarketplaceSupplySnapshot",
    "MarketplaceTrafficDay",
    "MarketplaceVariantCost",
    "Membership",
    "Notification",
    "NotificationSettings",
    "OtpChallenge",
    "OzonAnalyticsSync",
    "OzonCatalogSync",
    "ProductCost",
    "ProductMatch",
    "PushDevice",
    "RecoveryCode",
    "RefreshToken",
    "Store",
    "StoreCredential",
    "StoreEvent",
    "StoreGoal",
    "SupplyDestinationSnapshot",
    "SupplyDestinationSync",
    "SupplyPackaging",
    "SupplyPlan",
    "SyncRun",
    "SyncSchedule",
    "TaxSetting",
    "User",
    "WBDailyMetric",
    "WBMetricVersion",
    "WBRecord",
    "WBStagedRecord",
    "Workspace",
    "WorkspaceInvite",
]
