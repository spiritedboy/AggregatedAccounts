import hashlib
import hmac
import secrets
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AppSession

SESSION_COOKIE = "portfolio_session"
SESSION_TTL = timedelta(hours=12)

_attempts: dict[str, deque[datetime]] = defaultdict(deque)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() or request.client.host) if request.client else "unknown"


def check_login_rate_limit(ip: str) -> None:
    now = datetime.now(UTC)
    bucket = _attempts[ip]
    while bucket and bucket[0] < now - timedelta(minutes=5):
        bucket.popleft()
    if len(bucket) >= 8:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过多，请五分钟后重试",
        )
    bucket.append(now)


def clear_login_attempts(ip: str) -> None:
    _attempts.pop(ip, None)


async def create_session(db: AsyncSession, ip: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    session = AppSession(
        token_hash=digest(token),
        csrf_hash=digest(csrf),
        expires_at=datetime.now(UTC) + SESSION_TTL,
        client_ip=ip,
    )
    db.add(session)
    await db.commit()
    return token, csrf


async def require_session(
    portfolio_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> AppSession:
    if not portfolio_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    session = await db.scalar(
        select(AppSession).where(
            AppSession.token_hash == digest(portfolio_session),
            AppSession.expires_at > datetime.now(UTC),
        )
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="会话已过期")
    session.last_seen_at = datetime.now(UTC)
    return session


async def require_csrf(
    session: AppSession = Depends(require_session),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AppSession:
    if not csrf_token or not hmac.compare_digest(session.csrf_hash, digest(csrf_token)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")
    return session


async def revoke_session(db: AsyncSession, raw_token: str | None) -> None:
    if raw_token:
        await db.execute(delete(AppSession).where(AppSession.token_hash == digest(raw_token)))
        await db.commit()
