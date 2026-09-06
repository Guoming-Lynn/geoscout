from __future__ import annotations

from fastapi import Header, HTTPException, Request

from app.core.config import settings

SESSION_COOKIE = "geoscout_session"


def allowed_hosts() -> set[str]:
    return {"127.0.0.1", "localhost", settings.host}


def check_host(request: Request) -> None:
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    if host and host not in allowed_hosts():
        raise HTTPException(status_code=403, detail="Host 不被允许。本工具默认仅本机访问。")


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    if origin.rstrip("/") not in {item.rstrip("/") for item in settings.cors_origins}:
        raise HTTPException(status_code=403, detail="来源 Origin 不被允许。")


async def require_local_browser(request: Request) -> None:
    check_host(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)


def require_internal_token(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")) -> None:
    if not x_internal_token or x_internal_token != settings.internal_token:
        raise HTTPException(status_code=403, detail="内部凭据接口拒绝访问。")
