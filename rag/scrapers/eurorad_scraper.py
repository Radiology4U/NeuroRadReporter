#!/usr/bin/env python3
"""
Eurorad scraper for neuroradiology cases.
Eurorad (www.eurorad.org) is the European Society of Radiology's
open-access case library. Cases are published under open-access
terms for educational and research use.

We scrape only the text (findings, diagnosis, discussion) — no images.
Rate-limited to 1 request/sec. User-Agent identifies the project.
"""

import json
import time
import re
import requests
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data"

HEADERS = {
    "User-Agent": (
        "NeuroRadReporter-Research/1.0 "
        "(academic radiology AI research; "
        "github.com/Radiology4U/NeuroRadReporter)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Eurorad search terms focused on neuroradiology
SEARCH_TERMS = [
    "brain MRI glioblastoma",
    "brain MRI stroke diffusion",
    "multiple sclerosis brain MRI",
    "intracranial hemorrhage CT",
    "meningioma MRI",
    "brain metastases MRI",
    "cerebral abscess ring enhancing",
    "subarachnoid hemorrhage CT aneurysm",
    "cerebral venous thrombosis MRI",
    "herpes encephalitis MRI temporal",
    "PRES posterior reversible encephalopathy",
    "Wernicke encephalopathy MRI",
    "osmotic demyelination central pontine",
    "cerebral cavernoma MRI hemosiderin",
    "pituitary adenoma MRI sella",
    "craniopharyngioma MRI suprasellar",
    "medulloblastoma posterior fossa children",
    "primary CNS lymphoma MRI periventricular",
    "ADEM demyelination MRI",
    "focal cortical dysplasia MRI transmantle",
    "chiari malformation MRI syrinx",
    "spinal cord ischemia diffusion MRI",
]

BASE_URL = "https://www.eurorad.org"


def search_eurorad(term: str, max_pages: int = 2) -> list[dict]:
    """Search Eurorad and return case stubs {title, url}."""
    stubs = []
    for page in range(1, max_pages + 1):
        try:
            url = f"{BASE_URL}/search/{requests.utils.quote(term)}"
            params = {"page": page}
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if r.status_code == 404:
                break
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # Eurorad case listing format
            found = False
            for item in soup.select("article.case-teaser, div.views-row, li.case-item"):
                a = item.select_one("a[href*='/case/'], a[href*='/eurorad/case/']")
                if not a:
                    a = item.select_one("h2 a, h3 a, .case-title a")
                if not a:
                    continue
                href = a.get("href", "")
                if not href.startswith("http"):
                    href = BASE_URL + href
                title = a.get_text(strip=True)
                if href and title:
                    stubs.append({"title": title, "url": href})
                    found = True
            if not found:
                break
            time.sleep(1.0)
        except Exception as e:
            print(f"  Search error '{term}' page {page}: {e}")
            break
    return stubs


def scrape_case(url: str) -> dict | None:
    """Scrape a single Eurorad case page."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Title
        title_el = soup.select_one("h1.page-header, h1.case-title, h1")
        title = title_el.get_text(strip=True) if title_el else ""

        # Patient demographics (anonymised on Eurorad)
        demographics = ""
        for el in soup.select(".field-patient, .demographics, .patient-info"):
            demographics = el.get_text(separator=" ", strip=True)
            break

        # Clinical history / presentation
        presentation = _extract_section(soup,
            ["clinical history", "history", "presentation", "clinical information"])

        # Imaging findings
        findings = _extract_section(soup,
            ["imaging findings", "findings", "mri findings", "ct findings"])

        # Discussion / conclusion / diagnosis
        diagnosis = _extract_section(soup,
            ["discussion", "diagnosis", "conclusion", "differential diagnosis"])

        # Tags / keywords
        tags = [t.get_text(strip=True)
                for t in soup.select(".tag, .keyword, .field-tags a, .views-field-field-keywords a")]
        tags = [t for t in tags if t]

        content = " ".join(filter(None, [presentation, findings, diagnosis])).strip()
        if len(content) < 80:
            return None

        case_id = re.search(r"/case[s]?/(\d+)", url)
        case_id = case_id.group(1) if case_id else url.rstrip("/").split("/")[-1]

        return {
            "id":           f"eurorad_{case_id}",
            "source":       "eurorad",
            "title":        title,
            "demographics": demographics,
            "presentation": presentation,
            "findings":     findings,
            "diagnosis":    diagnosis,
            "abstract":     content,
            "tags":         tags,
            "url":          url,
            "attribution":  "© Eurorad / European Society of Radiology — open access educational use",
            "scraped_at":   datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"  Error scraping {url}: {e}")
        return None


def _extract_section(soup: BeautifulSoup, keywords: list[str]) -> str:
    """Find a section by heading keyword and return its text content."""
    # Try labelled field divs first
    for el in soup.select(".field, .section, .block, article section"):
        heading = el.select_one("h2, h3, h4, label, .field-label, .section-title")
        if heading:
            ht = heading.get_text(strip=True).lower()
            if any(kw in ht for kw in keywords):
                # Text is the element minus its heading
                for h in el.select("h2, h3, h4, label"):
                    h.decompose()
                return el.get_text(separator=" ", strip=True)[:1000]

    # Fallback: search all headings on the page
    for tag in soup.select("h2, h3, h4"):
        if any(kw in tag.get_text(strip=True).lower() for kw in keywords):
            # Collect sibling text nodes
            parts = []
            for sib in tag.next_siblings:
                if hasattr(sib, "name") and sib.name in ("h2", "h3", "h4"):
                    break
                parts.append(sib.get_text(separator=" ", strip=True)
                              if hasattr(sib, "get_text") else str(sib).strip())
            text = " ".join(p for p in parts if p).strip()
            if text:
                return text[:1000]
    return ""


def run_scraper(max_per_term: int = 8, output_file: str = "eurorad_cases.jsonl"):
    """Run all search terms, scrape cases, save JSONL."""
    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / output_file

    seen_urls: set[str] = set()
    if out_path.exists():
        with open(out_path) as f:
            for line in f:
                try:
                    seen_urls.add(json.loads(line)["url"])
                except Exception:
                    pass
    print(f"Already have {len(seen_urls)} Eurorad cases. Fetching new ones...\n")

    new_cases = 0
    with open(out_path, "a") as out:
        for term in SEARCH_TERMS:
            print(f"Searching Eurorad: {term}")
            stubs = search_eurorad(term)
            print(f"  → {len(stubs)} results")
            time.sleep(1.5)

            for stub in stubs[:max_per_term]:
                if stub["url"] in seen_urls:
                    continue
                time.sleep(1.2)
                case = scrape_case(stub["url"])
                if case:
                    out.write(json.dumps(case, ensure_ascii=False) + "\n")
                    seen_urls.add(stub["url"])
                    new_cases += 1
                    print(f"  ✓ {case['title'][:65]}…")

    print(f"\nDone. Added {new_cases} new Eurorad cases. Total: {len(seen_urls)}")
    return new_cases


if __name__ == "__main__":
    run_scraper()
