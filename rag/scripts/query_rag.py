#!/usr/bin/env python3
"""
RAG query module — given a radiology findings text, retrieve the most
similar cases from the vector DB and return them as context for Claude.

Can be called as a standalone script or imported as a module.
"""

import json
import os
from pathlib import Path

DB_DIR = Path(__file__).parent.parent / "data" / "chroma_db"


def get_embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb")


def get_collection():
    import chromadb
    client = chromadb.PersistentClient(path=str(DB_DIR))
    return client.get_collection("neurorad_cases")


def retrieve_similar_cases(
    query_text: str,
    n_results: int = 3,
    source_filter: str | None = None,
) -> list[dict]:
    """
    Given radiology findings text, return n most similar cases.

    Args:
        query_text: The findings/impression text to match
        n_results: Number of similar cases to return
        source_filter: Optional — "pubmed" or "radiopaedia" only

    Returns:
        List of dicts with title, diagnosis, url, source, similarity_score
    """
    embedder = get_embedder()
    collection = get_collection()

    query_embedding = embedder.encode([query_text]).tolist()

    where = {"source": source_filter} if source_filter else None

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=n_results,
        where=where,
        include=["metadatas", "distances", "documents"],
    )

    cases = []
    for i, (meta, dist, doc) in enumerate(zip(
        results["metadatas"][0],
        results["distances"][0],
        results["documents"][0],
    )):
        similarity = round(1 - dist, 3)  # cosine distance → similarity
        cases.append({
            "rank": i + 1,
            "title": meta.get("title", ""),
            "diagnosis": meta.get("diagnosis", ""),
            "source": meta.get("source", ""),
            "url": meta.get("url", ""),
            "year": meta.get("year", ""),
            "tags": meta.get("tags", ""),
            "similarity": similarity,
            "snippet": doc[:400],
        })

    return cases


def format_rag_context(cases: list[dict]) -> str:
    """Format retrieved cases as a context block for Claude's system prompt."""
    if not cases:
        return ""

    lines = ["## Similar cases from radiology literature\n"]
    for c in cases:
        lines.append(f"### {c['rank']}. {c['title']}")
        if c["diagnosis"]:
            lines.append(f"**Diagnosis:** {c['diagnosis'][:200]}")
        lines.append(f"**Similarity:** {c['similarity']:.0%} | **Source:** {c['source']} {c['year']}")
        if c["url"]:
            lines.append(f"**Reference:** {c['url']}")
        lines.append(f"\n{c['snippet']}\n")
    lines.append("---\nUse these cases as supporting evidence where relevant. Always indicate uncertainty.")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "T2 hyperintense lesion periventricular white matter multiple lesions"
    )
    print(f"Query: {query}\n")
    cases = retrieve_similar_cases(query, n_results=3)
    print(format_rag_context(cases))
