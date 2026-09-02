"""Application configuration.

Every tunable lives here so behaviour can be changed through environment
variables without touching code. Values are read once at import time.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv is optional - the app runs fine without a .env file
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover - defensive, never fatal
    pass


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DATASETS_DIR = BASE_DIR / "datasets"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "storage" / "uploads")))


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Runtime settings, resolved from the environment."""

    APP_NAME: str = "Resume Intelligence API"
    APP_VERSION: str = "1.0.0"
    DESCRIPTION: str = (
        "Company- and role-specific resume analysis: parsing, NLP skill extraction, "
        "explainable compatibility scoring, ATS review, truthful improvement suggestions, "
        "project recommendations and a personalised learning roadmap."
    )

    # --- Server -----------------------------------------------------------
    # Containers must bind 0.0.0.0; PaaS platforms inject PORT.
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    # Off by default so a deployment never leaks internals; run.py turns it on
    # for local development.
    DEBUG: bool = _flag("DEBUG", "false")

    # Comma-separated origins allowed to call the API. Default "*" suits a
    # public, unauthenticated API; name the frontend origin explicitly to lock
    # it down.
    CORS_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
    ]
    # Regex for dynamic frontend origins - Netlify mints a new hostname per
    # deploy preview, e.g. https://deploy-preview-12--my-site.netlify.app
    CORS_ORIGIN_REGEX: str = os.getenv("CORS_ORIGIN_REGEX", "")

    @property
    def cors_allows_any_origin(self) -> bool:
        return "*" in self.CORS_ORIGINS

    @property
    def cors_allow_credentials(self) -> bool:
        """Credentials are only meaningful with an explicit origin allowlist.

        Sending Access-Control-Allow-Credentials alongside a wildcard policy
        invites any site to make authenticated calls; this API has no auth, so
        credentials are simply disabled in that case.
        """
        return not self.cors_allows_any_origin

    # --- Database ---------------------------------------------------------
    # SQLite for development; set DATABASE_URL to a postgresql+psycopg:// URL
    # to run the identical schema on PostgreSQL.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'storage' / 'resume_intelligence.db').as_posix()}"
    )

    # --- Uploads ----------------------------------------------------------
    MAX_UPLOAD_MB: float = float(os.getenv("MAX_UPLOAD_MB", "10"))
    ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx", ".txt"}
    STORE_UPLOADED_FILES: bool = _flag("STORE_UPLOADED_FILES", "false")

    # --- NLP --------------------------------------------------------------
    SPACY_MODEL: str = os.getenv("SPACY_MODEL", "en_core_web_sm")
    ENABLE_SPACY: bool = _flag("ENABLE_SPACY", "true")

    # --- Generative AI (optional) ----------------------------------------
    # With no key configured the AI service falls back to a deterministic,
    # rule-based rewrite engine. Both paths obey the same honesty rules.
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-sonnet-5")
    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "1400"))
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)

    @property
    def max_upload_bytes(self) -> int:
        return int(self.MAX_UPLOAD_MB * 1024 * 1024)


settings = Settings()

# Storage directories are created eagerly so the first upload cannot fail on a
# missing folder.
(BASE_DIR / "storage").mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
