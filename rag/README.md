# NeuroRadReporter — RAG Knowledge Base

Continuously learns from neuroradiology literature and enriches AI-generated reports with similar real cases.

## Architecture

```
Radiopaedia + PubMed/NCBI
        ↓
  Python scrapers (weekly via GitHub Actions)
        ↓
  ChromaDB (local vector DB, BioBERT embeddings)
        ↓
  RAG server (port 8765)
        ↓
  NeuroRadReporter app → Claude API
        (similar cases injected into system prompt)
```

## Quick Start

### 1. Install dependencies
```bash
cd rag
pip install -r requirements.txt
```

### 2. Run scrapers (first time — takes ~10–20 min)
```bash
python scrapers/pubmed_scraper.py
python scrapers/radiopaedia_scraper.py
```

### 3. Build the vector index
```bash
python scripts/embed_and_index.py
```

### 4. Start the RAG server
```bash
python scripts/rag_server.py
# Running on http://localhost:8765
```

### 5. Connect in NeuroRadReporter
- Open Settings → RAG Knowledge Base
- Enter `http://localhost:8765`
- Click **Test connection**
- ✓ Reports now enriched with similar literature cases

## Weekly Automated Updates

GitHub Actions runs every Sunday at 02:00 UTC:
- Pulls new cases from PubMed + Radiopaedia
- Re-embeds and upserts into ChromaDB
- Commits updated `.jsonl` files to repo

Set `NCBI_API_KEY` in GitHub Secrets for higher PubMed rate limits (free at https://www.ncbi.nlm.nih.gov/account/).

## Data Sources

| Source | License | Cases |
|--------|---------|-------|
| PubMed Central | Open Access | Abstracts only |
| Radiopaedia | CC BY-NC-SA | Non-commercial, attribution required |
| Eurorad | Open Access | (add `scrapers/eurorad_scraper.py`) |

## Production Deployment

For SaaS: deploy `rag_server.py` on a small VPS (e.g. Fly.io, Hetzner CX11 ~€4/mo).
The ChromaDB folder (`data/chroma_db/`) is ~500MB for 10,000 cases.

Update your RAG Server URL in Settings to your production URL, e.g. `https://rag.yourdomain.com`.
