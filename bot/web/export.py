import csv
import io
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import StreamingResponse, JSONResponse
from starlette.routing import Route
from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import User, BoughtGoods, Operations, Payments


BATCH_SIZE = 1000


async def _stream_csv(query, columns, session_maker):
    """Generic CSV streamer that yields rows in batches."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(columns)
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)

    offset = 0
    while True:
        async with session_maker() as s:
            result = await s.execute(query.offset(offset).limit(BATCH_SIZE))
            rows = result.all()

        if not rows:
            break

        for row in rows:
            writer.writerow([getattr(row, c, row[i]) if hasattr(row, c) else row[i] for i, c in enumerate(columns)])

        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        offset += BATCH_SIZE


def _parse_date_params(request: Request):
    """Parse from/to date query params."""
    from_str = request.query_params.get("from")
    to_str = request.query_params.get("to")
    from_date = None
    to_date = None
    if from_str:
        try:
            from_date = datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if to_str:
        try:
            to_date = datetime.strptime(to_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return from_date, to_date


def _check_auth(request: Request):
    return request.session.get("authenticated", False)


async def export_users(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from_date, to_date = _parse_date_params(request)
    query = select(
        User.telegram_id, User.balance, User.role_id,
        User.referral_id, User.registration_date, User.is_blocked
    ).order_by(User.telegram_id)

    if from_date:
        query = query.where(User.registration_date >= from_date)
    if to_date:
        query = query.where(User.registration_date < to_date)

    columns = ["telegram_id", "balance", "role_id", "referral_id", "registration_date", "is_blocked"]

    return StreamingResponse(
        _stream_csv(query, columns, Database().session),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


async def export_purchases(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from_date, to_date = _parse_date_params(request)
    query = select(
        BoughtGoods.id, BoughtGoods.item_name, BoughtGoods.price,
        BoughtGoods.buyer_id, BoughtGoods.bought_datetime, BoughtGoods.unique_id
    ).order_by(BoughtGoods.id)

    if from_date:
        query = query.where(BoughtGoods.bought_datetime >= from_date)
    if to_date:
        query = query.where(BoughtGoods.bought_datetime < to_date)

    columns = ["id", "item_name", "price", "buyer_id", "bought_datetime", "unique_id"]

    return StreamingResponse(
        _stream_csv(query, columns, Database().session),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=purchases.csv"},
    )


async def export_operations(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from_date, to_date = _parse_date_params(request)
    query = select(
        Operations.id, Operations.user_id, Operations.operation_value,
        Operations.operation_time
    ).order_by(Operations.id)

    if from_date:
        query = query.where(Operations.operation_time >= from_date)
    if to_date:
        query = query.where(Operations.operation_time < to_date)

    columns = ["id", "user_id", "operation_value", "operation_time"]

    return StreamingResponse(
        _stream_csv(query, columns, Database().session),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=operations.csv"},
    )


async def export_payments(request: Request):
    if not _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from_date, to_date = _parse_date_params(request)
    query = select(
        Payments.id, Payments.provider, Payments.external_id,
        Payments.user_id, Payments.amount, Payments.currency,
        Payments.status, Payments.created_at
    ).order_by(Payments.id)

    if from_date:
        query = query.where(Payments.created_at >= from_date)
    if to_date:
        query = query.where(Payments.created_at < to_date)

    columns = ["id", "provider", "external_id", "user_id", "amount", "currency", "status", "created_at"]

    return StreamingResponse(
        _stream_csv(query, columns, Database().session),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )


export_routes = [
    Route("/export/users", export_users),
    Route("/export/purchases", export_purchases),
    Route("/export/operations", export_operations),
    Route("/export/payments", export_payments),
]
