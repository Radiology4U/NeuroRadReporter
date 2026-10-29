#!/usr/bin/env python3
"""
Embed scraped radiology cases and store in ChromaDB vector database.
Uses sentence-transformers (free, local, no API key needed).
Run after scraping to build/update the index.
"""

import json
import os
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_DIR = Path(__file__).parent.parent / "data" / "chroma_db"


def get_embedder():
    """Load sentence-transformer model (downloads once, ~90MB)."""
    try:
        from sentence_transformers import SentenceTransformer
        # BioBERT-based model fine-tuned on medical text — much better than generic
        model = SentenceTransformer("pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb")
        print("✓ Loaded BioBERT medical embedder")
        return model
    except ImportError:
        print("Installing sentence-transformers...")
        os.system("pip install sentence-transformers --break-system-packages -q")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb")
        return model


def get_chroma():
    """Initialize ChromaDB client."""
    try:
        import chromadb
    except ImportError:
        print("Installing chromadb...")
        os.system("pip install chromadb --break-system-packages -q")
        import chromadb

    DB_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_or_create_collection(
        name="neurorad_cases",
        metadata={"hnsw:space": "cosine"},
    )
    print(f"✓ ChromaDB collection: {collection.count()} existing cases")
    return collection


def build_embed_text(case: dict) -> str:
    """Build the text we embed — combines title + clinical content."""
    parts = [
        case.get("title", ""),
        case.get("findings", ""),
        case.get("diagnosis", ""),
        case.get("presentation", ""),
        case.get("abstract", ""),
    ]
    # Deduplicate and join
    seen = set()
    unique = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            unique.append(p)
    return " | ".join(unique)[:2000]  # cap at 2000 chars


def load_cases(source_files: list[str]) -> list[dict]:
    """Load all scraped cases from JSONL files."""
    cases = []
    for fname in source_files:
        path = DATA_DIR / fname
        if not path.exists():
            print(f"  (skipping {fname} — not found)")
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        cases.append(json.loads(line))
                    except Exception:
                        pass
        print(f"  Loaded {fname}")
    return cases


def embed_and_index(batch_size: int = 32):
    """Main pipeline: load → embed → upsert to ChromaDB."""
    print("=== NeuroRad RAG Indexer ===\n")

    collection = get_chroma()
    embedder = get_embedder()

    # Load from all scrapers
    cases = load_cases(["pubmed_cases.jsonl", "radiopaedia_cases.jsonl"])
    if not cases:
        print("No cases found. Run the scrapers first.")
        sys.exit(1)
    print(f"\nLoaded {len(cases)} total cases")

    # Filter out already-indexed
    existing_ids = set(collection.get(include=[])["ids"])
    new_cases = [c for c in cases if c["id"] not in existing_ids]
    print(f"New cases to index: {len(new_cases)}")

    if not new_cases:
        print("All cases already indexed. Nothing to do.")
        return

    # Embed in batches
    indexed = 0
    for i in range(0, len(new_cases), batch_size):
        batch = new_cases[i:i + batch_size]
        texts = [build_embed_text(c) for c in batch]
        embeddings = embedder.encode(texts, show_progress_bar=False).tolist()

        collection.upsert(
            ids=[c["id"] for c in batch],
            embeddings=embeddings,
            documents=texts,
            metadatas=[{
                "title": c.get("title", "")[:200],
                "source": c.get("source", ""),
                "url": c.get("url", ""),
                "year": str(c.get("year", "")),
                "tags": ", ".join(c.get("tags", [])[:10]),
                "diagnosis": c.get("diagnosis", c.get("abstract", ""))[:300],
            } for c in batch],
        )
        indexed += len(batch)
        print(f"  Indexed {indexed}/{len(new_cases)}...")

    print(f"\n✓ Done. Collection now has {collection.count()} cases.")


if __name__ == "__main__":
    embed_and_index()
