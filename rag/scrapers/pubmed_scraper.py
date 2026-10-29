#!/usr/bin/env python3
"""
PubMed Central scraper for neuroradiology case reports.
Pulls open-access case reports with findings + diagnosis.
No API key required for basic use; set NCBI_API_KEY env var for higher rate limits.
"""

import os
import json
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
API_KEY = os.environ.get("NCBI_API_KEY", "")
DATA_DIR = Path(__file__).parent.parent / "data"

NEURORAD_QUERIES = [
    "brain MRI case report findings diagnosis",
    "neuroradiology case report cerebral",
    "head CT case report neurological",
    "spine MRI case report diagnosis",
    "brain tumor MRI radiology case",
    "stroke MRI diffusion case report",
    "multiple sclerosis MRI brain case report",
    "intracranial hemorrhage CT case",
    "glioma MRI diagnosis radiology",
    "dementia MRI findings case report",
]


def search_pubmed(query: str, max_results: int = 50) -> list[str]:
    """Search PubMed and return list of PMIDs."""
    params = {
        "db": "pubmed",
        "term": f"{query}[Title/Abstract] AND free full text[Filter] AND case reports[Publication Type]",
        "retmax": max_results,
        "retmode": "json",
        "usehistory": "n",
    }
    if API_KEY:
        params["api_key"] = API_KEY

    r = requests.get(f"{NCBI_BASE}/esearch.fcgi", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_abstract(pmid: str) -> dict | None:
    """Fetch abstract and metadata for a PMID."""
    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml",
        "rettype": "abstract",
    }
    if API_KEY:
        params["api_key"] = API_KEY

    try:
        r = requests.get(f"{NCBI_BASE}/efetch.fcgi", params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)

        article = root.find(".//Article")
        if not article:
            return None

        title = article.findtext(".//ArticleTitle", "").strip()

        # Extract abstract sections
        abstract_parts = []
        for text in article.findall(".//AbstractText"):
            label = text.get("Label", "")
            content = (text.text or "").strip()
            if content:
                abstract_parts.append(f"{label}: {content}" if label else content)
        abstract = " ".join(abstract_parts)

        if not abstract or len(abstract) < 100:
            return None

        # Journal + year
        journal = article.findtext(".//Journal/Title", "")
        year = article.findtext(".//PubDate/Year", "")

        # MeSH terms as tags
        mesh_terms = [
            m.findtext("DescriptorName", "")
            for m in root.findall(".//MeshHeading")
        ]
        mesh_terms = [m for m in mesh_terms if m]

        return {
            "id": f"pubmed_{pmid}",
            "source": "pubmed",
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "journal": journal,
            "year": year,
            "tags": mesh_terms,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "scraped_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        print(f"  Error fetching PMID {pmid}: {e}")
        return None


def run_scraper(max_per_query: int = 30, output_file: str = "pubmed_cases.jsonl"):
    """Run all queries and save results."""
    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / output_file

    # Load already-scraped IDs to avoid duplicates
    seen_ids = set()
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                try:
                    seen_ids.add(json.loads(line)["pmid"])
                except Exception:
                    pass
    print(f"Already have {len(seen_ids)} cases. Fetching new ones...")

    new_cases = 0
    with open(out_path, "a") as out:
        for query in NEURORAD_QUERIES:
            print(f"\nQuery: {query}")
            pmids = search_pubmed(query, max_per_query)
            print(f"  Found {len(pmids)} PMIDs")

            for pmid in pmids:
                if pmid in seen_ids:
                    continue
                time.sleep(0.4 if API_KEY else 1.0)  # NCBI rate limits
                case = fetch_abstract(pmid)
                if case:
                    out.write(json.dumps(case) + "\n")
                    seen_ids.add(pmid)
                    new_cases += 1
                    print(f"  ✓ {pmid}: {case['title'][:60]}...")

    print(f"\nDone. Added {new_cases} new cases. Total: {len(seen_ids)}")
    return new_cases


if __name__ == "__main__":
    run_scraper()
