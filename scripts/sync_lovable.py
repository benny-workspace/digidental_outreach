"""Push daily outreach stats to Supabase, for the Lovable life planner.

One-way sync, on purpose. This laptop stays the source of truth for all
lead data. Only summary numbers go up: one row per day, upserted, so
running it twice in a day just refreshes today's row. Nothing ever syncs
back down, so nothing can conflict.

Needs internet and a config.local.yaml with your Supabase details
(copy config.local.example.yaml and fill it in). Without that file it
just prints instructions and exits. Phase 1 never needs this script.

Usage:
    python scripts\\sync_lovable.py

Or double-click "Sync Planner.bat" in the project folder.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import yaml

import db

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONFIG = BASE_DIR / "config.local.yaml"
TABLE = "outreach_daily"

POSITIVE_OUTCOMES = {"replied", "call_booked", "closed_won"}


def load_local_config():
    if not LOCAL_CONFIG.exists():
        return {}
    return yaml.safe_load(LOCAL_CONFIG.read_text(encoding="utf-8")) or {}


def compute_stats():
    leads = db.get_leads()
    outcomes = [(l.get("outcome") or "").strip() for l in leads]
    return {
        "day": date.today().isoformat(),
        "total_leads": len(leads),
        "drafts_ready": sum(1 for l in leads if l["status"] in ("drafts_generated", "reviewed")),
        "leads_contacted": sum(1 for l in leads if l["status"] == "exported"),
        "replies": sum(1 for o in outcomes if o in POSITIVE_OUTCOMES),
        "calls_booked": sum(1 for o in outcomes if o in ("call_booked", "closed_won")),
        "closed_won": sum(1 for o in outcomes if o == "closed_won"),
    }


def main():
    supabase = load_local_config().get("supabase", {})
    url = str(supabase.get("url", "")).strip()
    key = str(supabase.get("service_role_key", "")).strip()
    if not url or not key or "YOURPROJECT" in url or "PASTE_" in key:
        print("Supabase is not configured yet. To set it up:")
        print("1. Copy config.local.example.yaml to config.local.yaml")
        print("2. Fill in your Supabase project URL and service_role key")
        print("   (Supabase dashboard: Project Settings, then API)")
        print("3. Create the table once. SQL is in the README.")
        print("config.local.yaml stays on this laptop. It is never committed.")
        return

    db.init_db()
    stats = compute_stats()
    endpoint = url.rstrip("/") + f"/rest/v1/{TABLE}?on_conflict=day"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    try:
        response = requests.post(endpoint, headers=headers, json=[stats], timeout=30)
    except requests.RequestException as exc:
        print(f"Could not reach Supabase: {exc}")
        print("Check your internet connection. Nothing was changed locally.")
        sys.exit(1)
    if response.status_code >= 300:
        print(f"Supabase said no ({response.status_code}): {response.text[:300]}")
        print("Most common cause: the outreach_daily table does not exist yet.")
        print("Create it with the SQL in the README, then run this again.")
        sys.exit(1)
    print("Synced to the planner:")
    for name, value in stats.items():
        print(f"  {name}: {value}")


if __name__ == "__main__":
    main()
