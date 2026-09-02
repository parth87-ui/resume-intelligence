#!/usr/bin/env python
"""Single-command launcher.

    python run.py                 # start the API + dashboard on 127.0.0.1:8000
    python run.py --port 9000     # different port
    python run.py --check         # verify the environment and exit
    python run.py --seed          # (re)create and seed the database, then exit

Runs the FastAPI app from the ``backend`` package with the dashboard mounted at
``/``. Interactive API documentation is at ``/docs``.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND))

# run.py is the local development entry point, so debug is on unless the
# environment says otherwise. Deployments import the app directly (uvicorn
# main:app) and get the safe default from config.py.
os.environ.setdefault("DEBUG", "true")

REQUIRED = [
    ("fastapi", "FastAPI web framework", True),
    ("uvicorn", "ASGI server", True),
    ("sqlalchemy", "database layer", True),
    ("multipart", "file upload support (pip install python-multipart)", True),
]
OPTIONAL = [
    ("sklearn", "TF-IDF + cosine similarity (falls back to a NumPy implementation)"),
    ("spacy", "lemmatisation and NER (falls back to a regex pipeline)"),
    ("pymupdf", "PDF extraction (pdfplumber is used as a fallback)"),
    ("pdfplumber", "PDF extraction fallback"),
    ("docx", "DOCX extraction (python-docx)"),
]


def check_environment() -> bool:
    """Report which capabilities are available. Returns False if unrunnable."""
    # Plain ASCII: Windows consoles default to cp1252 and mangle box-drawing
    # and dash characters.
    print("Resume Intelligence - environment check\n" + "-" * 52)
    ok = True

    for module, description, _ in REQUIRED:
        try:
            importlib.import_module(module)
            print(f"  [ok]      {module:<15} {description}")
        except ImportError:
            ok = False
            print(f"  [MISSING] {module:<15} {description}")

    print()
    for module, description in OPTIONAL:
        try:
            importlib.import_module(module)
            print(f"  [ok]      {module:<15} {description}")
        except ImportError:
            print(f"  [absent]  {module:<15} {description}")

    # spaCy model is separate from the spaCy package.
    try:
        import spacy

        try:
            spacy.load("en_core_web_sm")
            print(f"  [ok]      {'en_core_web_sm':<15} spaCy English model")
        except OSError:
            print(
                f"  [absent]  {'en_core_web_sm':<15} spaCy English model - "
                "run: python -m spacy download en_core_web_sm"
            )
    except ImportError:
        pass

    print("-" * 52)
    if not ok:
        print("\nInstall the missing packages:\n    pip install -r backend/requirements.txt")
    else:
        print("\nReady. Start the app with:  python run.py")
    return ok


def seed_database() -> None:
    from db.database import init_db

    init_db()
    print("Database created and seeded from backend/datasets/*.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Resume Intelligence platform.")
    parser.add_argument("--host", default=None, help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="port (default 8000)")
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    parser.add_argument("--check", action="store_true", help="check the environment and exit")
    parser.add_argument("--seed", action="store_true", help="seed the database and exit")
    args = parser.parse_args()

    if args.check:
        return 0 if check_environment() else 1

    try:
        from config import settings
    except ImportError as exc:
        print(f"Could not import the backend ({exc}).")
        print("Install dependencies first:  pip install -r backend/requirements.txt")
        return 1

    if args.seed:
        seed_database()
        return 0

    host = args.host or settings.HOST
    port = args.port or settings.PORT

    import uvicorn

    print(f"\n  Dashboard   http://{host}:{port}/")
    print(f"  API docs    http://{host}:{port}/docs")
    print(f"  Health      http://{host}:{port}/api/health\n")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=args.reload or settings.DEBUG,
        reload_dirs=[str(BACKEND)] if (args.reload or settings.DEBUG) else None,
        app_dir=str(BACKEND),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
