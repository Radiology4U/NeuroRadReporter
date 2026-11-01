#!/usr/bin/env python3
"""
Build rag/cases.json — a single flat JSON file consumed by the static app.

Input:  rag/data/pubmed_cases.jsonl
        rag/data/eurorad_cases.jsonl
Output: rag/cases.json  (committed to repo, served by GitHub Pages)

The app fetches this file at startup and uses TF-IDF cosine similarity
to find the most relevant cases for the current report context.
No server required.

Each output record:
{
  "id":       "pubmed_12345678",
  "source":   "pubmed" | "eurorad",
  "title":    "...",
  "findings": "...",
  "diagnosis":"...",
  "abstract": "...",   # combined searchable text
  "tags":     ["..."],
  "url":      "https://...",
  "year":     "2023"
}
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime

DATA_DIR   = Path(__file__).parent.parent / "data"
OUTPUT     = Path(__file__).parent.parent.parent / "rag" / "cases.json"
# Also write to repo root rag/ so GitHub Pages serves it
OUTPUT_ALT = Path(__file__).parent.parent / "cases.json"

JSONL_SOURCES = [
    "pubmed_cases.jsonl",
    "eurorad_cases.jsonl",
]

# Minimum useful content length
MIN_ABSTRACT_LEN = 80


def clean(text: str) -> str:
    if not text:
        return ""
    # Strip HTML residue
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_abstract(case: dict) -> str:
    """Combine available text fields into a single searchable abstract."""
    parts = [
        case.get("title", ""),
        case.get("findings", ""),
        case.get("diagnosis", ""),
        case.get("presentation", ""),
        case.get("abstract", ""),
    ]
    seen, unique = set(), []
    for p in parts:
        p = clean(p)
        if p and p not in seen:
            seen.add(p)
            unique.append(p)
    return " | ".join(unique)[:3000]


def load_jsonl(fname: str) -> list[dict]:
    path = DATA_DIR / fname
    if not path.exists():
        print(f"  (not found: {fname})")
        return []
    cases = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    cases.append(json.loads(line))
                except Exception:
                    pass
    print(f"  Loaded {len(cases)} from {fname}")
    return cases


def deduplicate(cases: list[dict]) -> list[dict]:
    """Remove duplicates by id; prefer records with richer content."""
    by_id: dict[str, dict] = {}
    for c in cases:
        cid = c.get("id", "")
        if not cid:
            continue
        if cid not in by_id:
            by_id[cid] = c
        else:
            # Keep whichever has longer abstract
            existing_len = len(by_id[cid].get("abstract", ""))
            new_len      = len(c.get("abstract", ""))
            if new_len > existing_len:
                by_id[cid] = c
    return list(by_id.values())


def build_output_record(case: dict) -> dict | None:
    abstract = build_abstract(case)
    if len(abstract) < MIN_ABSTRACT_LEN:
        return None
    return {
        "id":       case.get("id", ""),
        "source":   case.get("source", ""),
        "title":    clean(case.get("title", ""))[:200],
        "findings": clean(case.get("findings", ""))[:800],
        "diagnosis":clean(case.get("diagnosis", ""))[:400],
        "abstract": abstract,
        "tags":     case.get("tags", [])[:15],
        "url":      case.get("url", ""),
        "year":     str(case.get("year", "")),
        "journal":  case.get("journal", ""),
    }


def main():
    print("=== Build static RAG cases.json ===\n")

    all_cases: list[dict] = []
    for fname in JSONL_SOURCES:
        all_cases.extend(load_jsonl(fname))

    if not all_cases:
        print("No cases found. Run scrapers first.")
        sys.exit(1)

    print(f"\nTotal raw: {len(all_cases)}")

    # Deduplicate
    all_cases = deduplicate(all_cases)
    print(f"After dedup: {len(all_cases)}")

    # Build output records
    records = []
    for case in all_cases:
        rec = build_output_record(case)
        if rec:
            records.append(rec)

    print(f"After quality filter: {len(records)}")

    # Sort by source then year (newest first)
    records.sort(key=lambda c: (c["source"], -(int(c["year"]) if c["year"].isdigit() else 0)))

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "count":        len(records),
        "sources": {
            "pubmed":  sum(1 for r in records if r["source"] == "pubmed"),
            "eurorad": sum(1 for r in records if r["source"] == "eurorad"),
        },
        "cases": records,
    }

    # Write to rag/cases.json (served by GitHub Pages)
    OUTPUT_ALT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_ALT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Written {len(records)} cases to {OUTPUT_ALT}")

    # Stats
    by_source = {}
    for r in records:
        by_source.setdefault(r["source"], 0)
        by_source[r["source"]] += 1
    for src, n in sorted(by_source.items()):
        print(f"  {src}: {n} cases")


if __name__ == "__main__":
    main()
