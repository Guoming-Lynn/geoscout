from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credentials import SessionCredentials, store
from app.core.security import SESSION_COOKIE, require_local_browser
from app.db.session import get_session


async def browser_guard(request: Request) -> None:
    await require_local_browser(request)


def session_creds(request: Request, response: Response) -> SessionCredentials:
    sid = request.cookies.get(SESSION_COOKIE)
    creds = store.get_or_create(sid)
    if sid != creds.session_id:
        response.set_cookie(
            SESSION_COOKIE,
            creds.session_id,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
        )
    return creds


def db_session() -> AsyncSession:
    raise RuntimeError("use get_session")


DbSession = Depends(get_session)
Guard = Depends(browser_guard)
Creds = Depends(session_creds)
