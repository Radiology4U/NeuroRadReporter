# Deploy RAG Server to Fly.io

**Cost:** Free tier (sleeps when idle) or ~$2–5/mo for always-on.  
**Time:** ~15 minutes first deploy (BioBERT model download + scraping).

---

## Prerequisites

Install the Fly CLI:
```bash
# macOS
brew install flyctl

# Linux / Windows WSL
curl -L https://fly.io/install.sh | sh
```

Sign up / log in (free):
```bash
fly auth signup   # or: fly auth login
```

---

## Deploy

From the root of your repo:

```bash
# 1. Create the app (first time only)
fly launch --config rag/deploy/fly.toml --no-deploy

# 2. Create a persistent volume for ChromaDB data (1GB free)
fly volumes create neurorad_rag_data --size 1 --region ams

# 3. Deploy
fly deploy --config rag/deploy/fly.toml

# 4. Watch logs (first deploy seeds the DB — takes ~15 min)
fly logs --config rag/deploy/fly.toml
```

Your RAG server will be live at:
```
https://neurorad-rag.fly.dev
```

---

## Connect to NeuroRadReporter

1. Open your app → **Settings → RAG Knowledge Base**
2. Enter: `https://neurorad-rag.fly.dev`
3. Click **Test connection** → ✓ Connected

---

## Weekly auto-update (optional)

The GitHub Actions workflow already runs every Sunday and commits new cases.  
To also re-embed on Fly after each scrape, add this secret:

```bash
fly secrets set FLY_API_TOKEN=$(fly auth token)
```

Then uncomment the re-deploy step in `.github/workflows/rag_update.yml`.

---

## Useful commands

```bash
fly status --config rag/deploy/fly.toml    # check machine status
fly logs   --config rag/deploy/fly.toml    # live logs
fly ssh console --config rag/deploy/fly.toml  # SSH into container
fly scale memory 2048 --config rag/deploy/fly.toml  # if OOM on embedding
```

## Cost

| Plan | Price | Notes |
|------|-------|-------|
| Free | $0 | Sleeps after 5 min idle, ~30s cold start |
| Always-on | ~$3/mo | `min_machines_running = 1` in fly.toml |

For a SaaS the cold start is acceptable — the app shows a spinner while RAG loads.
