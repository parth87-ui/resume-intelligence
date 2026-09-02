# Deployment

## The one constraint that shapes everything

**Netlify cannot run this backend.** Netlify serves static files and JS/TS
serverless functions; it has no Python runtime. The API here is FastAPI running
spaCy, scikit-learn, PyMuPDF and pandas — roughly 190 MB of native
dependencies that load a language model at startup. There is no configuration
that makes that run on Netlify.

So there are two shapes of deployment:

| | Frontend | Backend | Good when |
|---|---|---|---|
| **Split** | Netlify | Render / Railway / Fly | You want Netlify's CDN, custom domain and previews |
| **Single host** | served by FastAPI | Render / Railway / Fly | Simplest — one deploy, no CORS, no API URL to configure |

The single-host option is genuinely simpler: the Docker image already serves the
dashboard at `/` and the API at `/api/*` on the same origin. Use the split only
if you specifically want the frontend on Netlify.

---

## Split deploy (Netlify frontend + hosted API)

### Step 1 — put the code on GitHub

```bash
git init
git add .
git commit -m "Resume Intelligence"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

`.gitignore` already excludes `.env`, the SQLite database and generated sample
binaries.

### Step 2 — deploy the API

**Render (blueprint included).** New → Blueprint → select the repo. Render reads
[`render.yaml`](../render.yaml), builds the Dockerfile and exposes a health check
at `/api/health`. First build takes 5–10 minutes (the spaCy model downloads at
build time).

**Anything that runs a container** works the same way:

```bash
docker build -t resume-intelligence .
docker run --rm -p 8000:8000 -e DEBUG=false resume-intelligence
```

Fly.io: `fly launch --dockerfile Dockerfile`. Railway: point it at the repo; it
detects the Dockerfile. Cloud Run: `gcloud run deploy --source .` (set
`--memory 1Gi`).

When it is live, note the URL — `https://<name>.onrender.com`. Confirm it:

```bash
curl https://<name>.onrender.com/api/health
```

### Step 3 — deploy the frontend to Netlify

New site → import the same repo. [`netlify.toml`](../netlify.toml) sets
everything: publish directory `frontend`, the config-injection build step, SPA
redirects and security headers.

Then **set the environment variable** — this is the step everything depends on:

> Site settings → Environment variables → `API_BASE` = `https://<name>.onrender.com`

Redeploy. The build writes that URL into `frontend/config.js`, and the dashboard
calls your API instead of itself.

If you skip it, the site still loads but shows a **"Connect to your API"** panel
where the URL can be entered by hand (stored in `localStorage`). That is the
recovery path, not the intended setup.

### Step 4 — lock down CORS

The API defaults to `CORS_ORIGINS=*`, which lets any site call it. Once the
Netlify URL exists, set on the backend:

```
CORS_ORIGINS=https://your-site.netlify.app
CORS_ORIGIN_REGEX=https://.*--your-site\.netlify\.app
```

The regex keeps deploy previews working — Netlify gives every pull request a
different hostname. With an explicit allowlist the API also starts sending
`Access-Control-Allow-Credentials`; with `*` it deliberately does not, since
credentials plus a wildcard origin is a policy no browser should honour.

---

## Single-host deploy

Skip Netlify entirely. Deploy the Docker image and open its URL — FastAPI serves
the dashboard at `/`, the API at `/api/*` and the docs at `/docs`. No `API_BASE`,
no CORS configuration, no second service.

---

## Configuration reference

Set these on the backend host:

| Variable | Default | Notes |
|---|---|---|
| `PORT` | `8000` | Injected by most platforms; the image reads it |
| `HOST` | `127.0.0.1` (`0.0.0.0` in the image) | Must be `0.0.0.0` in a container |
| `DEBUG` | `false` | Leave off. On, it exposes exception detail in responses |
| `CORS_ORIGINS` | `*` | Comma-separated. Set to your frontend origin |
| `CORS_ORIGIN_REGEX` | *(empty)* | For deploy previews |
| `WEB_CONCURRENCY` | `1` | See the memory note below |
| `DATABASE_URL` | SQLite file | Set a `postgresql+psycopg://` URL to persist data |
| `MAX_UPLOAD_MB` | `10` | Also check your platform's own request limit |
| `STORE_UPLOADED_FILES` | `false` | Keep off: only extracted text is stored |
| `ANTHROPIC_API_KEY` | *(empty)* | Optional; enables generative rewrites |

On Netlify, only `API_BASE` matters.

---

## What to expect on a free tier

**Memory.** The process loads spaCy, scikit-learn, NumPy and pandas into
each worker. Expect ~300–400 MB resident with one worker. On a 512 MB instance,
one worker fits and two do not — scale with replicas, not `WEB_CONCURRENCY`.

**Cold starts.** Render's free tier sleeps after ~15 minutes idle and takes
30–60 s to wake, plus ~4 s for spaCy to load. The frontend's request timeout is
120 s, so a cold start still completes — the first request just feels slow. The
loading state covers it.

**Storage is ephemeral.** SQLite lives on the container filesystem, so stored
resumes and analyses reset on every deploy and sleep cycle. Analysis itself is
stateless and unaffected — only the history disappears. To keep it, attach
PostgreSQL, uncomment the `DATABASE_URL` block in `render.yaml`, and add
`psycopg[binary]` to `backend/requirements.txt`. The schema is unchanged.

**Build time.** 5–10 minutes, dominated by installing scikit-learn/pandas wheels
and downloading the spaCy model.

---

## Troubleshooting

**"returned a web page instead of API data"** — the frontend is calling itself.
`API_BASE` is unset or wrong on Netlify. Fix it and redeploy, or use the
connection panel to test a URL first.

**Requests blocked by CORS** — the browser console names the origin it sent. Add
exactly that to `CORS_ORIGINS` (scheme included, no trailing slash). Check the
response with:

```bash
curl -i https://<api>/api/health -H "Origin: https://your-site.netlify.app" | grep -i access-control
```

An allowed origin is echoed back in `access-control-allow-origin`; a blocked one
gets no such header.

**First request after idle times out** — a cold start on a sleeping free
instance. Retry, or move to a paid always-on tier.

**Analyses vanish** — expected on ephemeral storage. See "Storage is ephemeral".

**Frontend changes don't appear** — bump the `?v=` query on the asset links in
`frontend/index.html`. Browsers cache ES modules aggressively, and `config.js`
is served `no-store` precisely so the API URL is never stale.
