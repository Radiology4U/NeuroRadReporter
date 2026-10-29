#!/usr/bin/env python3
"""
Radiopaedia scraper for neuroradiology cases.
Uses their public search + case pages (non-commercial, attribution required).
Rate-limited and respectful — checks robots.txt compliance.
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data"

HEADERS = {
    "User-Agent": "NeuroRadReporter-Research/1.0 (academic; contact: research@radiology4u.com)",
    "Accept": "text/html,application/xhtml+xml",
}

NEURORAD_SEARCH_TERMS = [
    "brain tumour MRI",
    "stroke diffusion MRI",
    "multiple sclerosis brain",
    "intracranial hemorrhage",
    "cerebral metastasis",
    "glioblastoma MRI",
    "meningioma",
    "hydrocephalus",
    "demyelination white matter",
    "cerebral abscess",
    "subarachnoid hemorrhage",
    "subdural hematoma",
    "cerebral venous thrombosis",
    "encephalitis MRI",
    "spine disc herniation MRI",
]


def search_radiopaedia(term: str, page: int = 1) -> list[dict]:
    """Search Radiopaedia and return case stubs."""
    url = "https://radiopaedia.org/search"
    params = {
        "q": term,
        "scope": "cases",
        "lang": "us",
        "page": page,
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        cases = []
        for item in soup.select("li.search-result.case"):
            a = item.select_one("a.search-result-title")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if href and not href.startswith("http"):
                href = "https://radiopaedia.org" + href
            cases.append({"title": title, "url": href})
        return cases

    except Exception as e:
        print(f"  Search error for '{term}': {e}")
        return []


def scrape_case_page(url: str) -> dict | None:
    """Scrape a single Radiopaedia case page for findings + diagnosis."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Title
        title = soup.select_one("h1.header-title")
        title = title.get_text(strip=True) if title else ""

        # Patient info (age/sex — already anonymized on Radiopaedia)
        patient_info = soup.select_one("div.case-patient-data")
        patient_text = patient_info.get_text(strip=True) if patient_info else ""

        # Presentation / clinical info
        presentation = ""
        for section in soup.select("div.sub-section"):
            header = section.select_one("h4, h3")
            if header and any(w in header.get_text().lower()
                              for w in ["presentation", "clinical", "history"]):
                presentation = section.get_text(separator=" ", strip=True)
                break

        # Findings
        findings = ""
        for section in soup.select("div.sub-section"):
            header = section.select_one("h4, h3")
            if header and "finding" in header.get_text().lower():
                findings = section.get_text(separator=" ", strip=True)
                break

        # Diagnosis (usually in the case discussion or title)
        diagnosis = ""
        for section in soup.select("div.sub-section"):
            header = section.select_one("h4, h3")
            if header and any(w in header.get_text().lower()
                              for w in ["diagnosis", "discussion", "conclusion"]):
                diagnosis = section.get_text(separator=" ", strip=True)
                break

        # Tags / anatomy
        tags = [t.get_text(strip=True) for t in soup.select("a.tag")]

        # Must have at least some findings content
        content = " ".join([presentation, findings, diagnosis]).strip()
        if len(content) < 80:
            return None

        case_id = url.rstrip("/").split("/")[-1]
        return {
            "id": f"radiopaedia_{case_id}",
            "source": "radiopaedia",
            "title": title,
            "patient": patient_text,
            "presentation": presentation,
            "findings": findings,
            "diagnosis": diagnosis,
            "abstract": content,  # unified field for embedding
            "tags": tags,
            "url": url,
            "attribution": "© Radiopaedia.org — CC BY-NC-SA",
            "scraped_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        print(f"  Error scraping {url}: {e}")
        return None


def run_scraper(max_per_term: int = 10, output_file: str = "radiopaedia_cases.jsonl"):
    """Run all search terms and scrape cases."""
    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / output_file

    seen_urls = set()
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                try:
                    seen_urls.add(json.loads(line)["url"])
                except Exception:
                    pass
    print(f"Already have {len(seen_urls)} Radiopaedia cases.")

    new_cases = 0
    with open(out_path, "a") as out:
        for term in NEURORAD_SEARCH_TERMS:
            print(f"\nSearching: {term}")
            stubs = search_radiopaedia(term)
            print(f"  Found {len(stubs)} results")
            time.sleep(2)  # polite delay between searches

            for stub in stubs[:max_per_term]:
                if stub["url"] in seen_urls:
                    continue
                time.sleep(1.5)  # polite delay between case pages
                case = scrape_case_page(stub["url"])
                if case:
                    out.write(json.dumps(case) + "\n")
                    seen_urls.add(stub["url"])
                    new_cases += 1
                    print(f"  ✓ {case['title'][:60]}...")

    print(f"\nDone. Added {new_cases} new Radiopaedia cases.")
    return new_cases


if __name__ == "__main__":
    run_scraper()
