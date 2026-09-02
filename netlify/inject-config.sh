#!/usr/bin/env sh
# Netlify build step: bake the API location into the static bundle.
#
# Set API_BASE in the Netlify UI (Site settings -> Environment variables) to the
# public URL of the FastAPI backend, e.g. https://resume-intelligence.onrender.com
# Leaving it unset ships a same-origin default, which only works when something
# on the same host also serves /api.
set -e

API_BASE="${API_BASE:-}"
# Strip any trailing slashes so the client can concatenate paths safely.
API_BASE=$(printf '%s' "$API_BASE" | sed 's:/*$::')

cat > frontend/config.js <<EOF
/* Generated at build time by netlify/inject-config.sh - do not edit. */
window.__API_BASE__ = '${API_BASE}';
EOF

if [ -z "$API_BASE" ]; then
  echo "WARNING: API_BASE is not set. The deployed frontend will call its own"
  echo "         origin for /api/*, which Netlify cannot serve. Set API_BASE to"
  echo "         your FastAPI deployment URL and redeploy."
else
  echo "Frontend will call the API at: $API_BASE"
fi
