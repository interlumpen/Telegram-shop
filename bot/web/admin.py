import logging
import time
from typing import Any

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route
from sqlalchemy import text

from bot.misc import EnvKeys
from bot.database.methods.audit import log_audit

logger = logging.getLogger(__name__)


class LoginRateLimiter:
    """In-memory rate limiter for login attempts by IP."""

    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 900):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = {}

    def is_blocked(self, ip: str) -> bool:
        if ip not in self._attempts:
            return False
        now = time.time()
        # Clean old attempts
        self._attempts[ip] = [t for t in self._attempts[ip] if now - t < self.lockout_seconds]
        return len(self._attempts[ip]) >= self.max_attempts

    def record_failure(self, ip: str) -> None:
        now = time.time()
        if ip not in self._attempts:
            self._attempts[ip] = []
        self._attempts[ip].append(now)

    def reset(self, ip: str) -> None:
        self._attempts.pop(ip, None)


_login_limiter = LoginRateLimiter()
from bot.database.main import Database
from bot.database.models.main import (
    User, Role, Categories, Goods, ItemValues,
    BoughtGoods, Operations, Payments, ReferralEarnings,
    AuditLog,
)
from bot.misc.metrics import get_metrics
from bot.misc.caching import get_cache_manager


# Authentication
class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        ip = request.client.host

        if _login_limiter.is_blocked(ip):
            log_audit("web_login_blocked", level="WARNING", details=f"ip={ip}", ip_address=ip)
            return False

        form = await request.form()
        username = form.get("username")
        password = form.get("password")

        if username == EnvKeys.ADMIN_USERNAME and password == EnvKeys.ADMIN_PASSWORD:
            request.session.update({"authenticated": True})
            _login_limiter.reset(ip)
            log_audit("web_login", user_id=None, details=f"user={username}", ip_address=ip)
            return True

        _login_limiter.record_failure(ip)
        log_audit("web_login_failed", level="WARNING", details=f"user={username}", ip_address=ip)
        return False

    async def logout(self, request: Request) -> bool:
        log_audit("web_logout", ip_address=request.client.host)
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("authenticated", False)


# Audited base view for mutable models
class AuditModelView(ModelView):
    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        action = f"sqladmin_{'create' if is_created else 'update'}"
        log_audit(
            action,
            resource_type=self.name,
            resource_id=str(getattr(model, 'id', getattr(model, 'name', None))),
            details=repr(model),
            ip_address=request.client.host,
        )

    async def after_model_delete(self, model: Any, request: Request) -> None:
        log_audit(
            "sqladmin_delete",
            resource_type=self.name,
            resource_id=str(getattr(model, 'id', getattr(model, 'name', None))),
            details=repr(model),
            ip_address=request.client.host,
        )


# Model Views
class UserAdmin(AuditModelView, model=User):
    column_list = [User.telegram_id, User.balance, User.role_id, User.referral_id,
                   User.registration_date, User.is_blocked]
    column_searchable_list = [User.telegram_id]
    column_sortable_list = [User.telegram_id, User.balance, User.registration_date]
    column_default_sort = (User.registration_date, True)
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-users"


class RoleAdmin(AuditModelView, model=Role):
    column_list = [Role.id, Role.name, Role.default, Role.permissions]
    column_details_exclude_list = ["users"]
    column_sortable_list = [Role.id, Role.name]
    name = "Role"
    name_plural = "Roles"
    icon = "fa-solid fa-shield-halved"


class CategoryAdmin(AuditModelView, model=Categories):
    column_list = [Categories.name]
    column_searchable_list = [Categories.name]
    name = "Category"
    name_plural = "Categories"
    icon = "fa-solid fa-folder"


class GoodsAdmin(AuditModelView, model=Goods):
    column_list = [Goods.id, Goods.name, Goods.price, Goods.description, Goods.category_id]
    column_searchable_list = [Goods.name]
    column_sortable_list = [Goods.id, Goods.name, Goods.price]
    name = "Product"
    name_plural = "Products"
    icon = "fa-solid fa-box"


class ItemValuesAdmin(AuditModelView, model=ItemValues):
    column_list = [ItemValues.id, ItemValues.item_id, ItemValues.value, ItemValues.is_infinity]
    column_searchable_list = [ItemValues.value]
    column_sortable_list = [ItemValues.id, ItemValues.item_id]
    name = "Stock Item"
    name_plural = "Stock Items"
    icon = "fa-solid fa-warehouse"


class BoughtGoodsAdmin(ModelView, model=BoughtGoods):
    column_list = [BoughtGoods.id, BoughtGoods.item_name, BoughtGoods.value,
                   BoughtGoods.price, BoughtGoods.buyer_id, BoughtGoods.bought_datetime,
                   BoughtGoods.unique_id]
    column_searchable_list = [BoughtGoods.item_name, BoughtGoods.buyer_id, BoughtGoods.unique_id]
    column_sortable_list = [BoughtGoods.id, BoughtGoods.bought_datetime, BoughtGoods.price]
    column_default_sort = (BoughtGoods.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Purchase"
    name_plural = "Purchases"
    icon = "fa-solid fa-cart-shopping"


class OperationsAdmin(ModelView, model=Operations):
    column_list = [Operations.id, Operations.user_id, Operations.operation_value,
                   Operations.operation_time]
    column_searchable_list = [Operations.user_id]
    column_sortable_list = [Operations.id, Operations.operation_time, Operations.operation_value]
    column_default_sort = (Operations.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Operation"
    name_plural = "Operations"
    icon = "fa-solid fa-money-bill-transfer"


class PaymentsAdmin(ModelView, model=Payments):
    column_list = [Payments.id, Payments.provider, Payments.external_id, Payments.user_id,
                   Payments.amount, Payments.currency, Payments.status, Payments.created_at]
    column_searchable_list = [Payments.user_id, Payments.external_id, Payments.provider]
    column_sortable_list = [Payments.id, Payments.created_at, Payments.amount, Payments.status]
    column_default_sort = (Payments.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Payment"
    name_plural = "Payments"
    icon = "fa-solid fa-credit-card"


class ReferralEarningsAdmin(ModelView, model=ReferralEarnings):
    column_list = [ReferralEarnings.id, ReferralEarnings.referrer_id,
                   ReferralEarnings.referral_id, ReferralEarnings.amount,
                   ReferralEarnings.original_amount, ReferralEarnings.created_at]
    column_searchable_list = [ReferralEarnings.referrer_id, ReferralEarnings.referral_id]
    column_sortable_list = [ReferralEarnings.id, ReferralEarnings.created_at, ReferralEarnings.amount]
    column_default_sort = (ReferralEarnings.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Referral Earning"
    name_plural = "Referral Earnings"
    icon = "fa-solid fa-handshake"


class AuditLogAdmin(ModelView, model=AuditLog):
    column_list = [AuditLog.id, AuditLog.timestamp, AuditLog.level, AuditLog.user_id,
                   AuditLog.action, AuditLog.resource_type, AuditLog.resource_id,
                   AuditLog.details, AuditLog.ip_address]
    column_searchable_list = [AuditLog.action, AuditLog.resource_type, AuditLog.details]
    column_sortable_list = [AuditLog.id, AuditLog.timestamp, AuditLog.level, AuditLog.action]
    column_default_sort = (AuditLog.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Audit Log"
    name_plural = "Audit Logs"
    icon = "fa-solid fa-clipboard-list"


# Health & Metrics Endpoints
async def health_check(request: Request) -> JSONResponse:
    health_status = {
        "status": "healthy",
        "checks": {},
    }

    try:
        with Database().session() as s:
            s.execute(text("SELECT 1"))
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        health_status["checks"]["database"] = f"error: {e}"
        health_status["status"] = "unhealthy"

    cache = get_cache_manager()
    health_status["checks"]["redis"] = "ok" if cache else "not configured"

    metrics = get_metrics()
    if metrics:
        health_status["checks"]["metrics"] = "ok"
        health_status["uptime"] = metrics.get_metrics_summary()["uptime_seconds"]

    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(health_status, status_code=status_code)


async def prometheus_metrics(request: Request) -> PlainTextResponse:
    if not request.session.get("authenticated"):
        return PlainTextResponse("Unauthorized", status_code=401)
    metrics = get_metrics()
    if not metrics:
        return PlainTextResponse("# Metrics not initialized\n", status_code=503)
    return PlainTextResponse(metrics.export_to_prometheus(), media_type="text/plain")


async def metrics_json(request: Request) -> JSONResponse:
    if not request.session.get("authenticated"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    metrics = get_metrics()
    if not metrics:
        return JSONResponse({"error": "Metrics not initialized"}, status_code=503)
    return JSONResponse(metrics.get_metrics_summary(), status_code=200)


# App Factory
def create_admin_app() -> Starlette:
    if "change-me" in EnvKeys.SECRET_KEY.lower():
        logger.warning("SECRET_KEY is using default value! Change it in .env for production")

    routes = [
        Route("/health", health_check),
        Route("/metrics", metrics_json),
        Route("/metrics/prometheus", prometheus_metrics),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(SessionMiddleware, secret_key=EnvKeys.SECRET_KEY)

    auth_backend = AdminAuth(secret_key=EnvKeys.SECRET_KEY)
    admin = Admin(
        app,
        engine=Database().engine,
        authentication_backend=auth_backend,
        title="Telegram Shop Admin",
    )

    admin.add_view(UserAdmin)
    admin.add_view(RoleAdmin)
    admin.add_view(CategoryAdmin)
    admin.add_view(GoodsAdmin)
    admin.add_view(ItemValuesAdmin)
    admin.add_view(BoughtGoodsAdmin)
    admin.add_view(OperationsAdmin)
    admin.add_view(PaymentsAdmin)
    admin.add_view(ReferralEarningsAdmin)
    admin.add_view(AuditLogAdmin)

    return app
