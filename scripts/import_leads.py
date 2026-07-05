"""Import a lead CSV into the database and score each lead.

Usage:
    python scripts\\import_leads.py path\\to\\leads.csv

Scoring is deterministic. No network calls, no LLM, instant.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db

YES_VALUES = {"y", "yes", "true", "1"}
NO_VALUES = {"n", "no", "false", "0"}


def norm_flag(value):
    """Return 'Y', 'N', or '' for unknown. Only explicit values count."""
    text = (value or "").strip().lower()
    if text in YES_VALUES:
        return "Y"
    if text in NO_VALUES:
        return "N"
    return ""


def parse_review_count(value):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return 0


def compute_score(lead):
    """Deterministic intent score. Returns (score, disqualified)."""
    score = 0
    if lead["evening_or_saturday_hours"] == "Y":
        score += 2
    if lead["has_chatbot"] == "N":
        score += 2
    if lead["single_location"] == "Y":
        score += 1
    if lead["mentions_emergency_or_same_day"] == "Y":
        score += 1
    if 0 < lead["review_count"] < 20:
        score += 1
    if lead["has_after_hours_number"] == "N":
        score += 1
    disqualified = lead["already_has_ai_receptionist"] == "Y"
    if disqualified:
        score -= 5
    return score, disqualified


def import_csv(csv_path):
    """Import every row of the CSV. Returns a summary dict."""
    db.init_db()
    summary = {"imported": 0, "disqualified": 0, "duplicates": 0, "errors": []}
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for line_number, row in enumerate(reader, start=2):
            clinic_name = (row.get("clinic_name") or "").strip()
            if not clinic_name:
                summary["errors"].append(
                    f"Line {line_number}: missing clinic_name, row skipped."
                )
                continue
            location = (row.get("location") or "").strip()
            if db.lead_exists(clinic_name, location):
                summary["duplicates"] += 1
                continue
            lead = {
                "clinic_name": clinic_name,
                "owner_first_name": (row.get("owner_first_name") or "").strip(),
                "website": (row.get("website") or "").strip(),
                "location": location,
                "phone": (row.get("phone") or "").strip(),
                "email": (row.get("email") or "").strip(),
                "source": (row.get("source") or "").strip(),
                "notes": (row.get("notes") or "").strip(),
                "evening_or_saturday_hours": norm_flag(row.get("evening_or_saturday_hours")),
                "single_location": norm_flag(row.get("single_location")),
                "has_chatbot": norm_flag(row.get("has_chatbot")),
                "mentions_emergency_or_same_day": norm_flag(row.get("mentions_emergency_or_same_day")),
                "review_count": parse_review_count(row.get("review_count")),
                "has_after_hours_number": norm_flag(row.get("has_after_hours_number")),
                "already_has_ai_receptionist": norm_flag(row.get("already_has_ai_receptionist")),
            }
            score, disqualified = compute_score(lead)
            lead["intent_score"] = score
            lead["status"] = "skipped" if disqualified else "imported"
            db.insert_lead(lead)
            if disqualified:
                summary["disqualified"] += 1
            else:
                summary["imported"] += 1
    return summary


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts\\import_leads.py path\\to\\leads.csv")
        sys.exit(1)
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)
    summary = import_csv(csv_path)
    print(f"Imported: {summary['imported']}")
    print(f"Disqualified (already uses an AI receptionist): {summary['disqualified']}")
    print(f"Duplicates skipped: {summary['duplicates']}")
    for error in summary["errors"]:
        print(error)


if __name__ == "__main__":
    main()
