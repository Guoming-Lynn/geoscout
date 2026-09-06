from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api import internal, router
from app.core.config import settings
from app.core.redact import redact_text
from app.db.session import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("geoscout")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    logger.info("GEOScout API listening intent host=%s port=%s", settings.host, settings.port)
    yield


app = FastAPI(title="GEOScout", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(internal)


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    logger.exception("unhandled: %s", redact_text(str(exc)))
    return JSONResponse({"detail": "服务器内部错误。请查看本地日志（已脱敏）。"}, status_code=500)


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
