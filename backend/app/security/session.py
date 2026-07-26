from fastapi import Depends, Header, HTTPException, Request, status


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() or request.client.host) if request.client else "unknown"


async def require_session() -> None:
    return None


async def require_csrf(
    _: None = Depends(require_session),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    del csrf_token
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="公开只读模式不允许通过网站修改账户或触发写操作",
    )
