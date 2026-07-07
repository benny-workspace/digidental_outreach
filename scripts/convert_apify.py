"""Convert an Apify Google Maps scrape CSV into the lead import format.

Usage:
    python scripts\\convert_apify.py input.csv output.csv

Maps the Apify columns (title, categoryName, address, city, phone,
emails/0, domain, reviewsCount) onto the header import_leads.py expects.
The manual signal columns (evening_or_saturday_hours, single_location,
has_chatbot, mentions_emergency_or_same_day, has_after_hours_number,
already_has_ai_receptionist) are left blank for the operator to fill in
by hand before importing. No network calls, no LLM, instant.
"""

import csv
import sys
from pathlib import Path

IMPORT_COLUMNS = [
    "clinic_name", "website", "location", "phone", "email", "source", "notes",
    "evening_or_saturday_hours", "single_location", "has_chatbot",
    "mentions_emergency_or_same_day", "review_count",
    "has_after_hours_number", "already_has_ai_receptionist",
]


def convert_row(row):
    """Map one Apify row onto the import columns. Returns None if unusable."""
    clinic_name = (row.get("title") or "").strip()
    if not clinic_name:
        return None
    category = (row.get("categoryName") or "").strip()
    address = (row.get("address") or "").strip()
    converted = {column: "" for column in IMPORT_COLUMNS}
    converted["clinic_name"] = clinic_name
    converted["website"] = (row.get("domain") or "").strip()
    converted["location"] = (row.get("city") or "").strip()
    converted["phone"] = (row.get("phone") or "").strip()
    converted["email"] = (row.get("emails/0") or "").strip()
    converted["source"] = "Apify"
    converted["notes"] = " | ".join(part for part in (category, address) if part)
    converted["review_count"] = (row.get("reviewsCount") or "").strip()
    return converted


def convert_csv(input_path, output_path):
    """Convert the whole file. Returns (written, skipped) row counts."""
    written = 0
    skipped = 0
    with open(input_path, newline="", encoding="utf-8-sig") as infile:
        reader = csv.DictReader(infile)
        with open(output_path, "w", newline="", encoding="utf-8") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=IMPORT_COLUMNS)
            writer.writeheader()
            for row in reader:
                converted = convert_row(row)
                if converted is None:
                    skipped += 1
                    continue
                writer.writerow(converted)
                written += 1
    return written, skipped


def main():
    if len(sys.argv) != 3:
        print("Usage: python scripts\\convert_apify.py input.csv output.csv")
        sys.exit(1)
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    if not input_path.exists():
        print(f"File not found: {input_path}")
        sys.exit(1)
    written, skipped = convert_csv(input_path, output_path)
    print(f"Wrote {written} leads to {output_path}")
    if skipped:
        print(f"Skipped {skipped} rows with no clinic name.")


if __name__ == "__main__":
    main()
