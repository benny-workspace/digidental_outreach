"""Tenant-aware company profile and sales line library.

All business-specific text lives in JSON files under tenants/<tenant_id>/,
editable from the Admin page in the app. Nothing here requires a code
change to update the company, the offer, or the sales lines.

Files per tenant:
    company.json      the company profile (edited in Admin)
    sales_lines.json  the reference sales line library (edited in Reference)
    versions/         timestamped copies saved on every profile change
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import db

BASE_DIR = Path(__file__).resolve().parent
TENANTS_DIR = BASE_DIR / "tenants"

SALES_CATEGORIES = ("pain", "curiosity", "objection", "proof", "cta", "follow_up")
LINE_STATUSES = ("active", "preferred", "retired")

# Generic skeleton for a brand-new tenant. No business specifics here.
DEFAULT_PROFILE = {
    "company_name": "",
    "founder_name": "",
    "product_name": "",
    "calendar_name": "your calendar",
    "offer_summary": "",
    "pricing_summary": "",
    "target_customer": "",
    "services": [],
    "brand_voice": [],
    "pain_points": [],
    "proof_points": [],
    "prohibited_phrases": [],
    "contact_email": "",
    "website": "",
    "demo_url": "",
    "social_links": {},
    "channel_rules": {},
    "fallback_rules": "",
}


def tenant_dir():
    return TENANTS_DIR / db.active_tenant()


def profile_path():
    return tenant_dir() / "company.json"


def sales_lines_path():
    return tenant_dir() / "sales_lines.json"


def versions_dir():
    return tenant_dir() / "versions"


def _read_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback


def load_profile():
    """Profile with every expected key present, even for old files."""
    profile = dict(DEFAULT_PROFILE)
    profile.update(_read_json(profile_path(), {}))
    return profile


def save_profile(profile):
    """Save the profile, keeping a timestamped version for restore."""
    tenant_dir().mkdir(parents=True, exist_ok=True)
    versions_dir().mkdir(parents=True, exist_ok=True)
    if profile_path().exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(profile_path(), versions_dir() / f"company_{stamp}.json")
    profile_path().write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_profile_versions():
    if not versions_dir().exists():
        return []
    return sorted((p.name for p in versions_dir().glob("company_*.json")), reverse=True)


def restore_profile_version(name):
    source = versions_dir() / name
    if not source.exists():
        raise FileNotFoundError(name)
    restored = _read_json(source, {})
    save_profile(restored)
    return restored


def load_sales_lines():
    """{category: [{"text": ..., "status": active|preferred|retired}, ...]}"""
    lines = _read_json(sales_lines_path(), {})
    for category in SALES_CATEGORIES:
        lines.setdefault(category, [])
    return lines


def save_sales_lines(lines):
    tenant_dir().mkdir(parents=True, exist_ok=True)
    sales_lines_path().write_text(
        json.dumps(lines, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def check_prohibited(text):
    """Return the prohibited phrases found in the text. Empty list is a pass."""
    profile = load_profile()
    hits = []
    lowered = (text or "").lower()
    for phrase in profile.get("prohibited_phrases", []):
        if phrase and phrase.lower() in lowered:
            hits.append(phrase)
    if "—" in (text or "") and "—" not in hits:
        hits.append("em dash")
    return hits
