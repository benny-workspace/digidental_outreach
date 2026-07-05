"""Export approved messages to text files.

For every lead with at least one approved message, writes one text file
per approved message into exports\\<clinic_slug>\\, marks those messages
exported, and writes one combined CSV.

Usage:
    python scripts\\export.py
"""

import csv
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db

BASE_DIR = Path(__file__).resolve().parent.parent
EXPORTS_DIR = BASE_DIR / "exports"

CSV_COLUMNS = [
    "clinic_name", "location", "phone", "email", "intent_score",
] + list(db.MESSAGE_TYPES)


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "clinic"


def export_all():
    """Export every ready lead. Returns {'folders': [...], 'csv_path': ...}."""
    db.init_db()
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ready = db.get_export_ready_leads()
    folders = []
    csv_rows = []
    used_slugs = set()
    for lead in ready:
        approved = {
            m["message_type"]: m
            for m in db.get_messages_for_lead(lead["id"])
            if m["status"] == "approved"
        }
        if not approved:
            continue
        slug = slugify(lead["clinic_name"])
        if slug in used_slugs:
            slug = f"{slug}_{lead['id']}"
        used_slugs.add(slug)
        folder = EXPORTS_DIR / slug
        folder.mkdir(parents=True, exist_ok=True)
        row = {
            "clinic_name": lead["clinic_name"],
            "location": lead["location"],
            "phone": lead["phone"],
            "email": lead["email"],
            "intent_score": lead["intent_score"],
        }
        for message_type in db.MESSAGE_TYPES:
            message = approved.get(message_type)
            if message is None:
                row[message_type] = ""
                continue
            content = message["content_edited"] or message["content_generated"] or ""
            (folder / f"{message_type}.txt").write_text(content, encoding="utf-8")
            row[message_type] = content
            db.set_message_status(message["id"], "exported")
        db.set_lead_status(lead["id"], "exported")
        folders.append(folder)
        csv_rows.append(row)
    csv_path = None
    if csv_rows:
        csv_path = EXPORTS_DIR / f"all_approved_{date.today().isoformat()}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(csv_rows)
    return {"folders": folders, "csv_path": csv_path}


def main():
    result = export_all()
    if not result["folders"]:
        print("Nothing to export. A lead is ready when all three messages are approved.")
        return
    for folder in result["folders"]:
        print(f"Exported: {folder}")
    print(f"Combined CSV: {result['csv_path']}")


if __name__ == "__main__":
    main()
