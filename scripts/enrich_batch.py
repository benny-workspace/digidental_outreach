"""Phase 2 enrichment batch. Optional. Command line only, never run from the app.

Scrapes each lead's website, asks a local Ollama model for a short factual
summary and a sharper outreach angle, and stores both on the lead record.
Draft generation prefers the enriched angle when it exists.

Phase 1 never needs this script. If Ollama is not installed, everything
else keeps working.

Usage:
    python scripts\\enrich_batch.py --limit 2    (test on a couple of leads first)
    python scripts\\enrich_batch.py              (full batch, run it before bed)

Close heavy browser sessions before running a large batch. The model needs the RAM.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import yaml
from bs4 import BeautifulSoup

import db

BASE_DIR = Path(__file__).resolve().parent.parent


def load_config():
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def build_system_prompt(config):
    import company
    profile = company.load_profile()
    template = (BASE_DIR / "prompts" / "llm_system_prompt.txt").read_text(encoding="utf-8")
    return template.format_map(defaultdict(str, {
        "founder_name": str(profile.get("founder_name") or config.get("founder_name", "")),
        "company_name": str(profile.get("company_name", "")),
    }))


def ollama_is_running(config):
    url = config.get("ollama", {}).get("url", "http://localhost:11434/api/generate")
    base = url.split("/api/")[0]
    try:
        requests.get(base, timeout=5)
        return True
    except requests.RequestException:
        return False


def fetch_page_text(url, max_chars):
    if not url.lower().startswith("http"):
        url = "https://" + url
    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:max_chars]


def parse_model_json(raw):
    """Best-effort JSON parse. Returns {} instead of crashing the batch."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {}


def call_ollama(config, lead, page_text):
    ollama = config.get("ollama", {})
    prompt = (
        f"Clinic name: {lead['clinic_name']}\n"
        f"Location: {lead['location'] or 'unknown'}\n"
        f"Operator notes: {lead['notes'] or 'none'}\n\n"
        f"Website text:\n{page_text}"
    )
    payload = {
        "model": ollama.get("model", "llama3.2:1b"),
        "system": build_system_prompt(config),
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    response = requests.post(
        ollama.get("url", "http://localhost:11434/api/generate"),
        json=payload,
        timeout=ollama.get("timeout_seconds", 300),
    )
    response.raise_for_status()
    raw = response.json().get("response", "")
    data = parse_model_json(raw)
    summary = str(data.get("summary", "")).strip()
    angle = str(data.get("angle", "")).strip()
    return summary, angle


def main():
    parser = argparse.ArgumentParser(description="Phase 2 enrichment batch (optional).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only attempt the first N leads (for testing)")
    args = parser.parse_args()

    print("Reminder: close heavy browser sessions before running a large batch.")

    config = load_config()
    if not ollama_is_running(config):
        print("Ollama is not reachable at localhost:11434.")
        print("Start Ollama and try again. Phase 1 keeps working without this.")
        sys.exit(1)

    db.init_db()
    leads = db.get_leads(status="imported")
    candidates = [l for l in leads if not (l["enrichment_angle"] or "").strip()]
    if not candidates:
        print("Nothing to enrich. No 'imported' leads without an enrichment angle.")
        return

    attempts = 0
    enriched = 0
    for lead in candidates:
        if args.limit is not None and attempts >= args.limit:
            break
        website = (lead["website"] or "").strip()
        if not website:
            print(f"Lead {lead['id']} ({lead['clinic_name']}): no website, skipped.")
            continue
        print(f"Lead {lead['id']} ({lead['clinic_name']}): fetching site...")
        try:
            max_chars = config.get("enrichment", {}).get("max_page_chars", 4000)
            page_text = fetch_page_text(website, max_chars)
        except Exception as exc:
            print(f"  Could not fetch site, skipped. ({exc})")
            continue
        if not page_text.strip():
            print("  Page had no readable text, skipped.")
            continue
        attempts += 1
        print("  Asking the local model. This can take a minute or two on CPU...")
        try:
            summary, angle = call_ollama(config, lead, page_text)
        except Exception as exc:
            print(f"  Model call failed, skipped. ({exc})")
            continue
        if not summary and not angle:
            print("  Model output was not usable JSON. Lead left unchanged.")
            continue
        db.set_lead_enrichment(lead["id"], summary, angle)
        enriched += 1
        print("  Saved summary and angle.")

    print(f"Done. Model calls attempted: {attempts}. Leads enriched: {enriched}.")


if __name__ == "__main__":
    main()
