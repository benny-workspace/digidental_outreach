"""Import a lead CSV into the database and score each lead.

Usage:
    python scripts\\import_leads.py path\\to\\leads.csv

Headers are auto-detected (see csv_mapper.py). The app shows a mapping
review screen first; this CLI trusts the auto-detection and prints it.
Every raw row is preserved on the lead even when columns are unmapped.
Scoring is deterministic. No network calls, no LLM, instant.
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
import csv_mapper

YES_VALUES = {"y", "yes", "true", "1"}
NO_VALUES = {"n", "no", "false", "0"}

SOCIAL_FIELDS = csv_mapper.SOCIAL_FIELDS


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
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return 0


def compute_score(lead):
    """Deterministic intent score. Returns (score, disqualified).

    The signals are generic defaults. Customize qualification logic or profile
    rules for a specific business before relying on the score.
    """
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


def read_csv_rows(csv_path):
    """Headers and all rows, tolerant of BOMs and blank lines."""
    with open(csv_path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        reader = csv.reader(fh)
        rows = [row for row in reader if any(str(c).strip() for c in row)]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def detect(csv_path):
    """Auto-detect the mapping for a CSV. Returns (headers, proposals)."""
    headers, rows = read_csv_rows(csv_path)
    return headers, csv_mapper.detect_mapping(headers, rows[:20])


def _build_lead(header_map, headers, row):
    """One normalized lead dict from a raw CSV row, plus warnings."""
    raw = {}
    values = {}
    for index, header in enumerate(headers):
        cell = str(row[index]).strip() if index < len(row) else ""
        raw[header] = cell
        field = header_map.get(header)
        if field and cell and field not in values:
            values[field] = cell

    warnings = []
    business_name = values.get("business_name", "")
    if not business_name:
        # A contact name alone can still identify the lead.
        business_name = values.get("contact_name", "")
        if business_name:
            warnings.append("no business name, used contact name")
    first_name = values.get("first_name", "")
    last_name = values.get("last_name", "")
    contact_name = values.get("contact_name", "") or f"{first_name} {last_name}".strip()
    owner_first = values.get("owner_first_name", "") or first_name or (
        contact_name.split()[0] if contact_name else ""
    )
    social_links = {f: values[f] for f in SOCIAL_FIELDS if values.get(f)}

    if not any([values.get("email"), values.get("phone"), social_links,
                values.get("website")]):
        warnings.append("no contact method (email, phone, social, or website)")

    lead = {
        "clinic_name": business_name,
        "owner_first_name": owner_first,
        "first_name": first_name,
        "last_name": last_name,
        "role_title": values.get("role_title", ""),
        "industry": values.get("industry", ""),
        "niche": values.get("niche", ""),
        "website": values.get("website", ""),
        "location": values.get("location", ""),
        "phone": values.get("phone", ""),
        "email": values.get("email", ""),
        "social_links": json.dumps(social_links),
        "source": values.get("source", ""),
        "notes": values.get("notes", ""),
        "raw_columns": json.dumps(raw, ensure_ascii=False),
        "evening_or_saturday_hours": norm_flag(values.get("evening_or_saturday_hours")),
        "single_location": norm_flag(values.get("single_location")),
        "has_chatbot": norm_flag(values.get("has_chatbot")),
        "mentions_emergency_or_same_day": norm_flag(values.get("mentions_emergency_or_same_day")),
        "review_count": parse_review_count(values.get("review_count")),
        "has_after_hours_number": norm_flag(values.get("has_after_hours_number")),
        "already_has_ai_receptionist": norm_flag(values.get("already_has_ai_receptionist")),
    }
    return lead, warnings


def import_with_mapping(csv_path, header_map, source_file=None):
    """Import a CSV with a confirmed {header: field} mapping.

    Returns a summary dict including the import batch id.
    """
    db.init_db()
    source_file = source_file or Path(csv_path).name
    headers, rows = read_csv_rows(csv_path)
    summary = {"imported": 0, "disqualified": 0, "duplicates": 0, "errors": []}
    pending = []
    for line_number, row in enumerate(rows, start=2):
        lead, warnings = _build_lead(header_map, headers, row)
        if not lead["clinic_name"]:
            summary["errors"].append(
                f"Line {line_number}: no business or contact name, row skipped."
            )
            continue
        for warning in warnings:
            summary["errors"].append(f"Line {line_number} ({lead['clinic_name']}): {warning}")
        if db.lead_exists(lead["clinic_name"], lead["location"]):
            summary["duplicates"] += 1
            continue
        score, disqualified = compute_score(lead)
        lead["intent_score"] = score
        lead["status"] = "skipped" if disqualified else "imported"
        lead["source_file"] = source_file
        pending.append((lead, disqualified))

    batch_id = db.create_import_batch(source_file, header_map, summary)
    for lead, disqualified in pending:
        lead["import_batch_id"] = batch_id
        db.insert_lead(lead)
        if disqualified:
            summary["disqualified"] += 1
        else:
            summary["imported"] += 1
    db.update_import_batch(batch_id, summary)
    summary["batch_id"] = batch_id
    return summary


def import_csv(csv_path):
    """Auto-detected import, kept for the CLI and backward compatibility."""
    headers, proposals = detect(csv_path)
    return import_with_mapping(csv_path, csv_mapper.mapping_to_dict(proposals))


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts\\import_leads.py path\\to\\leads.csv")
        sys.exit(1)
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)
    headers, proposals = detect(csv_path)
    print("Detected mapping (review in the app for full control):")
    for proposal in proposals:
        target = proposal["field"] or "(raw only)"
        print(f"  {proposal['header']} -> {target} "
              f"[{proposal['confidence']:.2f}] {proposal['reason']}")
    summary = import_with_mapping(csv_path, csv_mapper.mapping_to_dict(proposals))
    print(f"Imported: {summary['imported']}")
    print(f"Disqualified: {summary['disqualified']}")
    print(f"Duplicates skipped: {summary['duplicates']}")
    for error in summary["errors"]:
        print(error)


if __name__ == "__main__":
    main()
