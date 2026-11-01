#!/usr/bin/env python3
"""
PubMed Central scraper for neuroradiology case reports.
Uses NCBI eutils (esearch + efetch) — explicitly allowed for text mining.
Fetches full-text abstracts via PubMed; for open-access articles also
retrieves structured full text via the BioC PMC API.

License: PMC Open Access Subset — Creative Commons / similar licenses.
Bulk download via NCBI APIs is explicitly permitted:
  https://www.ncbi.nlm.nih.gov/pmc/tools/openftlist/

Rate limits:
  - Without API key: 3 requests/second → we use 1 req/sec to be safe
  - With NCBI_API_KEY env var: 10 req/sec → 0.15 sec delay

Set NCBI_API_KEY in GitHub Secrets (free at https://www.ncbi.nlm.nih.gov/account/)
"""

import os
import json
import time
import re
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BIOC_BASE = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi"
API_KEY   = os.environ.get("NCBI_API_KEY", "")
DELAY     = 0.15 if API_KEY else 1.0
DATA_DIR  = Path(__file__).parent.parent / "data"

# Queries designed to find case reports with imaging findings + diagnosis
NEURORAD_QUERIES = [
    # Vascular
    "acute ischaemic stroke MRI DWI brain case report findings",
    "intracerebral haemorrhage CT brain case report",
    "subarachnoid haemorrhage CT aneurysm case report",
    "cerebral venous thrombosis MRI brain case report",
    "basilar artery occlusion MRI brainstem case report",
    # Tumours
    "glioblastoma MRI brain diagnosis radiology case report",
    "brain metastases MRI ring enhancement case report",
    "meningioma MRI brain radiology diagnosis case",
    "primary CNS lymphoma MRI periventricular case report",
    "medulloblastoma posterior fossa MRI children case report",
    # Demyelination / inflammatory
    "multiple sclerosis MRI white matter lesions case report",
    "ADEM acute disseminated encephalomyelitis MRI case report",
    "neurosarcoidosis leptomeningeal MRI case report",
    # Infection
    "cerebral abscess ring enhancing DWI restriction case report",
    "herpes simplex encephalitis temporal lobe MRI case report",
    # Metabolic / toxic
    "Wernicke encephalopathy MRI mammillary body case report",
    "osmotic demyelination central pontine myelinolysis MRI case",
    "PRES posterior reversible encephalopathy syndrome MRI case",
    # Congenital / developmental
    "focal cortical dysplasia MRI transmantle sign case report",
    "Chiari malformation MRI syringomyelia case report",
    # Spine
    "spinal cord infarction MRI diffusion restriction case report",
    "cervical myelopathy MRI cord signal case report",
    # Paediatric
    "paediatric brain tumour MRI diagnosis case report",
    "neonatal hypoxic ischaemic encephalopathy MRI case report",
    # Rarer entities worth including
    "MELAS mitochondrial encephalopathy MRI case report",
    "CNS vasculitis MRI angiography case report",
]


def search_pubmed(query: str, max_results: int = 40) -> list[str]:
    """Search PubMed; return list of PMIDs."""
    params = {
        "db": "pubmed",
        "term": (
            f"({query})[Title/Abstract]"
            " AND (free full text[Filter] OR open access[Filter])"
            " AND (case reports[Publication Type]"
            "   OR \"case report\"[Title/Abstract]"
            "   OR \"imaging findings\"[Title/Abstract])"
        ),
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }
    if API_KEY:
        params["api_key"] = API_KEY
    try:
        r = requests.get(f"{NCBI_BASE}/esearch.fcgi", params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"  esearch error: {e}")
        return []


def fetch_abstract(pmid: str) -> dict | None:
    """Fetch structured abstract + metadata for one PMID."""
    params = {"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"}
    if API_KEY:
        params["api_key"] = API_KEY
    try:
        r = requests.get(f"{NCBI_BASE}/efetch.fcgi", params=params, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)

        article = root.find(".//Article")
        if not article:
            return None

        title = (article.findtext(".//ArticleTitle") or "").strip()
        # Strip XML markup residue from title
        title = re.sub(r"<[^>]+>", "", title).strip()

        # Structured abstract (BACKGROUND / FINDINGS / CONCLUSION etc.)
        findings, diagnosis, abstract = "", "", ""
        for text_el in article.findall(".//AbstractText"):
            label = (text_el.get("Label") or "").upper()
            content = (text_el.text or "").strip()
            if not content:
                continue
            if any(w in label for w in ["FIND", "IMAGING", "RADIOLOG"]):
                findings = content
            elif any(w in label for w in ["DIAGNO", "CONCLUS", "IMPRESSION"]):
                diagnosis = content
            abstract += (f"[{label}] " if label else "") + content + " "

        abstract = abstract.strip()
        if len(abstract) < 80:
            return None

        # Check for open-access PMC link so we can optionally pull full text
        pmc_id = root.findtext(".//ArticleId[@IdType='pmc']") or ""

        journal = article.findtext(".//Journal/Title") or ""
        year    = article.findtext(".//PubDate/Year") or \
                  article.findtext(".//PubDate/MedlineDate", "")[:4]

        mesh_terms = [
            (m.findtext("DescriptorName") or "").strip()
            for m in root.findall(".//MeshHeading")
        ]
        mesh_terms = [m for m in mesh_terms if m]

        return {
            "id":       f"pubmed_{pmid}",
            "source":   "pubmed",
            "pmid":     pmid,
            "pmc_id":   pmc_id,
            "title":    title,
            "findings": findings,
            "diagnosis":diagnosis,
            "abstract": abstract,
            "journal":  journal,
            "year":     year,
            "tags":     mesh_terms,
            "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "scraped_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"  efetch error PMID {pmid}: {e}")
        return None


def enrich_with_bioc(case: dict) -> dict:
    """
    If a PMC ID is available, fetch structured full text via BioC JSON API
    and extract richer findings/diagnosis text.
    PMC OA BioC API: https://ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC
    """
    pmc_id = case.get("pmc_id", "").strip()
    if not pmc_id:
        return case
    try:
        url = f"{BIOC_BASE}/BioC_json/{pmc_id}/unicode"
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return case
        data = r.json()

        # BioC structure: {documents: [{passages: [{infons: {type}, text}]}]}
        findings_parts, diagnosis_parts = [], []
        for doc in data.get("documents", []):
            for passage in doc.get("passages", []):
                ptype = (passage.get("infons", {}).get("type") or "").lower()
                ptext = (passage.get("text") or "").strip()
                if not ptext or len(ptext) < 20:
                    continue
                if any(w in ptype for w in ["result", "finding", "case", "imaging"]):
                    findings_parts.append(ptext)
                elif any(w in ptype for w in ["conclusion", "diagnosis", "impression"]):
                    diagnosis_parts.append(ptext)

        if findings_parts:
            case["findings"] = " ".join(findings_parts)[:1500]
        if diagnosis_parts:
            case["diagnosis"] = " ".join(diagnosis_parts)[:800]
        case["full_text_source"] = "bioc_pmc"
    except Exception:
        pass  # BioC enrichment is best-effort
    return case


def run_scraper(max_per_query: int = 30, output_file: str = "pubmed_cases.jsonl"):
    """Run all queries, fetch abstracts (+ BioC enrichment), save JSONL."""
    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / output_file

    seen_pmids: set[str] = set()
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                try:
                    seen_pmids.add(json.loads(line)["pmid"])
                except Exception:
                    pass
    print(f"Already have {len(seen_pmids)} PubMed cases. Fetching new ones...")
    print(f"Rate: {'10 req/s (API key)' if API_KEY else '1 req/s (no key)'}\n")

    new_cases = 0
    with open(out_path, "a") as out:
        for query in NEURORAD_QUERIES:
            print(f"Query: {query[:70]}…")
            time.sleep(DELAY)
            pmids = search_pubmed(query, max_per_query)
            print(f"  → {len(pmids)} PMIDs")

            for pmid in pmids:
                if pmid in seen_pmids:
                    continue
                time.sleep(DELAY)
                case = fetch_abstract(pmid)
                if not case:
                    continue
                # Optional BioC enrichment for open-access articles
                if case.get("pmc_id"):
                    time.sleep(DELAY)
                    case = enrich_with_bioc(case)
                out.write(json.dumps(case, ensure_ascii=False) + "\n")
                seen_pmids.add(pmid)
                new_cases += 1
                print(f"  ✓ {pmid}: {case['title'][:65]}…")

    print(f"\nDone. Added {new_cases} new cases. Total stored: {len(seen_pmids)}")
    return new_cases


if __name__ == "__main__":
    run_scraper()
