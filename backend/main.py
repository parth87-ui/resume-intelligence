"""FastAPI application entry point.

Run from the ``backend`` directory:

    uvicorn main:app --reload

or from the project root:

    python run.py

Interactive API documentation is served at /docs (Swagger) and /redoc.
The dashboard is served at / from the ``frontend`` directory.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Allow `python main.py` and `uvicorn main:app` from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from api.routes import analysis, catalog, chat, resume  # noqa: E402
from config import FRONTEND_DIR, settings  # noqa: E402
from db.database import init_db  # noqa: E402
from ml.nlp_pipeline import get_pipeline  # noqa: E402
from ml.similarity_model import get_similarity_model  # noqa: E402
from schemas import HealthResponse  # noqa: E402
from services.ai_service import get_ai_service  # noqa: E402
from services.knowledge_base import get_knowledge_base  # noqa: E402

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("resume-intelligence")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load the knowledge base, database and NLP models once, at startup."""
    kb = get_knowledge_base()
    logger.info(
        "Knowledge base loaded: %d companies, %d roles, %d skills, %d projects, %d curated targets",
        len(kb.companies), len(kb.roles), len(kb.skills), len(kb.projects), len(kb.overrides),
    )
    try:
        init_db()
        logger.info("Database ready at %s", settings.DATABASE_URL.split("///")[-1])
    except Exception as exc:  # the API still works without persistence
        logger.error("Database initialisation failed (%s). Analyses will not be stored.", exc)

    logger.info("NLP backend: %s", get_pipeline().backend_detail)
    logger.info("Similarity: %s", get_similarity_model().method)
    logger.info("AI engine: %s", get_ai_service().engine_info()["mode"])
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "catalog", "description": "Companies, roles, levels, skills and scoring rules."},
        {"name": "resume", "description": "Upload, parse and retrieve resumes."},
        {"name": "analysis", "description": "Matching, scoring, ATS, recommendations and roadmaps."},
        {"name": "assistant", "description": "Grounded career assistant."},
        {"name": "system", "description": "Health and diagnostics."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time-Ms"],
)


# ---------------------------------------------------------------------------
# Middleware & error handling
# ---------------------------------------------------------------------------


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    # In debug mode the frontend is edited live; browser caching of the ES
    # modules and stylesheets is the number one cause of "my change did nothing".
    if settings.DEBUG and not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Return a readable message instead of raw pydantic internals."""
    problems = [
        {
            "field": ".".join(str(p) for p in error.get("loc", []) if p != "body"),
            "message": error.get("msg", "invalid value"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed.",
            "code": "validation_error",
            "problems": problems,
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):  # pragma: no cover
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred while processing the request.",
            "code": "internal_error",
            "hint": str(exc) if settings.DEBUG else None,
        },
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(catalog.router)
app.include_router(resume.router)
app.include_router(analysis.router)
app.include_router(chat.router)


@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    kb = get_knowledge_base()
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        nlp_backend=get_pipeline().info(),
        similarity_method=get_similarity_model().method,
        ai_engine=get_ai_service().engine_info(),
        datasets={
            "companies": len(kb.companies),
            "roles": len(kb.roles),
            "skills": len(kb.skills),
            "projects": len(kb.projects),
            "curated_targets": len(kb.overrides),
            "levels": len(kb.levels),
        },
    )


# The dashboard is served last so /api/* always wins the route match.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:  # pragma: no cover
    @app.get("/", tags=["system"])
    def missing_frontend() -> dict[str, str]:
        return {
            "message": f"{settings.APP_NAME} is running. Frontend directory not found.",
            "docs": "/docs",
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
