"""FastAPI application: analytics API + static React dashboard.

Run locally with::

    uvicorn api.main:app --host 0.0.0.0 --port 8000

The same process serves the compiled SPA from ``frontend/dist`` so the browser
URL is a single origin (no CORS or proxy needed in production).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import runtime
from api.routes_analytics import router as analytics_router
from api.routes_ops import router as ops_router
from api.routes_orders import router as orders_router
from common.db import healthcheck
from common.logging import configure_logging, new_request_id, request_id_var
from common.settings import PROJECT_ROOT, settings

logger = logging.getLogger("api")

configure_logging(settings.log_level)

DESCRIPTION = """
End-to-end e-commerce analytics platform: synthetic order generation → Kafka-style
event bus → medallion lake (bronze/silver/gold) → PostgreSQL star schema → dbt →
FastAPI → dashboard.

* Every value is computed from the warehouse on request; nothing is hardcoded.
* Date windows default to the last 90 days ending on the latest order date.
* `category` and `region` filters narrow every aggregate consistently.
* Forecast rows are model output, returned separately from observed history.
"""

app = FastAPI(
    title=runtime.APP_NAME,
    version=runtime.VERSION,
    description=DESCRIPTION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    contact={"name": "Divakar", "url": "https://www.accio.com/work/doc"},
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "unhandled error",
            extra={"extra_fields": {"method": request.method, "path": request.url.path}},
        )
        request_id_var.reset(token)
        raise
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
    if not request.url.path.startswith(("/assets", "/favicon")):
        logger.info(
            "%s %s %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={
                "extra_fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": elapsed_ms,
                }
            },
        )
    request_id_var.reset(token)
    return response


def _error(status: int, message, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"status": status, "message": message, "request_id": request_id}},
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, exc.detail, request_id_var.get())


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return _error(422, exc.errors(), request_id_var.get())


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.exception("unhandled exception", extra={"extra_fields": {"path": request.url.path}})
    return _error(500, f"{type(exc).__name__}: {exc}", request_id_var.get())


@app.on_event("startup")
async def startup() -> None:
    ok, detail = healthcheck()
    if ok:
        logger.info("database ready: %s", str(detail).split(",")[0])
    else:
        logger.error("database unavailable: %s", detail)


app.include_router(analytics_router)
app.include_router(orders_router)
app.include_router(ops_router)


@app.get("/api", tags=["meta"], summary="API index")
def api_index() -> dict:
    return {
        "name": runtime.APP_NAME,
        "version": runtime.VERSION,
        "docs": "/api/docs",
        "openapi": "/api/openapi.json",
        "endpoints": sorted(
            {route.path for route in app.routes if getattr(route, "methods", None) and route.path.startswith(("/api", "/health"))}
        ),
    }


# --------------------------------------------------------------------------- #
# static SPA
# --------------------------------------------------------------------------- #
DIST: Path = Path(settings.frontend_dist)
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    icon = DIST / "favicon.ico"
    if icon.exists():
        return FileResponse(icon)
    return JSONResponse(status_code=204, content=None)


@app.get("/", include_in_schema=False)
@app.get("/{path:path}", include_in_schema=False)
def spa(path: str = ""):
    """Serve the compiled React app, letting client-side routing own deep links."""
    # Unknown API/asset paths must not fall through to the SPA shell: a caller
    # asking for JSON should get a JSON 404, not an HTML document with status 200.
    if path.startswith(("api/", "assets/")):
        return _error(404, f"Unknown route: /{path}", request_id_var.get())
    index = DIST / "index.html"
    if not index.exists():
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "status": 503,
                    "message": "Dashboard bundle not built yet. Run `npm install && npm run build` in ./frontend.",
                    "request_id": request_id_var.get(),
                }
            },
        )
    candidate = (DIST / path).resolve()
    if path and candidate.is_file() and DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(index)


_ = PROJECT_ROOT
