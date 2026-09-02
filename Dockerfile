# Resume Intelligence - API image.
#
# Serves the FastAPI backend and, at the same origin, the static dashboard.
# That means this one image is a complete deployment: point a browser at it and
# everything works. Hosting the frontend separately (Netlify) is optional and
# only needs the API from this image.
#
#   docker build -t resume-intelligence .
#   docker run --rm -p 8000:8000 resume-intelligence
#
# Two stages so the ~500 MB of build tooling never reaches the final image.

# --------------------------------------------------------------- builder ----
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Wheels exist for every dependency on manylinux, so no compiler is needed.
COPY backend/requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt

# The spaCy model is a separate download from the spaCy package. Baking it into
# the image keeps startup offline and deterministic; without it the NLP pipeline
# silently degrades to its regex backend.
RUN /opt/venv/bin/python -m spacy download en_core_web_sm

# ---------------------------------------------------------------- runtime ----
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Containers must listen on all interfaces; PaaS platforms override PORT.
    HOST=0.0.0.0 \
    PORT=8000 \
    DEBUG=false

# libgomp1 is required by scikit-learn's OpenMP kernels; curl is used by the
# container healthcheck. Nothing else is needed - all wheels are self-contained.
RUN apt-get update \
 && apt-get install --no-install-recommends -y libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY run.py ./

# Writable storage for the SQLite database and any retained uploads. On an
# ephemeral filesystem this resets on redeploy - set DATABASE_URL to PostgreSQL
# if analyses must survive.
RUN mkdir -p /app/backend/storage \
 && useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# spaCy loads at startup (~4s), so allow a generous start period before the
# container is considered unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# One worker by default: every request loads the same in-process singletons
# (spaCy model, skill patterns, TF-IDF), so each extra worker costs another
# ~300 MB of RAM. Scale with replicas rather than workers on small instances.
CMD ["sh", "-c", "exec uvicorn main:app --app-dir backend --host ${HOST} --port ${PORT} --workers ${WEB_CONCURRENCY:-1} --timeout-keep-alive 65"]
