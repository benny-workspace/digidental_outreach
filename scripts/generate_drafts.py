"""Generate the three outreach drafts for a lead.

Usage:
    python scripts\\generate_drafts.py 3        (one lead, by id)
    python scripts\\generate_drafts.py --all    (every lead with status 'imported')

Plain string substitution against the files in prompts\\.
No LLM, no network calls, instant.
"""

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

import db

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"

# Deterministic angle rules for Phase 1. Checked in this order.
DETERMINISTIC_ANGLES = {
    "evening": {
        "angle_line": "Evening and Saturday hours usually mean after-hours calls that go straight to voicemail.",
        "pain_point": "your hours run into evenings and Saturdays, so calls come in when nobody can pick up",
        "one_line_value_prop": "Denty answers the evening and Saturday calls your front desk cannot reach.",
    },
    "emergency": {
        "angle_line": "Same-day and emergency requests are exactly the calls that get missed when the front desk is already busy.",
        "pain_point": "you take same-day and emergency requests, and those calls cannot wait for a callback",
        "one_line_value_prop": "Denty picks up emergency and same-day calls the moment the front desk cannot.",
    },
    "default": {
        "angle_line": "A missed call during a busy front desk moment is often a booking that goes to the next clinic instead.",
        "pain_point": "busy front desk moments send some calls to voicemail, and voicemail loses bookings",
        "one_line_value_prop": "Denty catches the calls that would otherwise go to voicemail and books them.",
    },
}


def load_config():
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_template(message_type):
    return (PROMPTS_DIR / f"{message_type}.txt").read_text(encoding="utf-8")


def format_day(d):
    return f"{d.strftime('%B')} {d.day}"


def previous_contact_date(lead_id):
    """Date of the existing first_contact message, or today if there is none."""
    for message in db.get_messages_for_lead(lead_id):
        if message["message_type"] == "first_contact" and message["created_at"]:
            try:
                return format_day(datetime.fromisoformat(message["created_at"]).date())
            except ValueError:
                break
    return format_day(date.today())


def pick_angles(lead):
    """Deterministic angles by default. Phase 2 enrichment wins when present."""
    if lead["evening_or_saturday_hours"] == "Y":
        angles = dict(DETERMINISTIC_ANGLES["evening"])
    elif lead["mentions_emergency_or_same_day"] == "Y":
        angles = dict(DETERMINISTIC_ANGLES["emergency"])
    else:
        angles = dict(DETERMINISTIC_ANGLES["default"])
    enriched_angle = (lead.get("enrichment_angle") or "").strip()
    if enriched_angle:
        angles["angle_line"] = enriched_angle
        angles["pain_point"] = enriched_angle
    return angles


def build_context(lead, config):
    """All template values. defaultdict(str) so a missing key renders empty."""
    angles = pick_angles(lead)
    owner = (lead.get("owner_first_name") or "").strip() or "there"
    context = {
        "owner_first_name": owner,
        "clinic_name": lead["clinic_name"],
        "founder_name": str(config.get("founder_name", "")),
        "calendar_name": str(config.get("calendar_name", "your Google Calendar")),
        "previous_date": previous_contact_date(lead["id"]),
        "angle_line": angles["angle_line"],
        "pain_point": angles["pain_point"],
        "one_line_value_prop": angles["one_line_value_prop"],
    }
    return defaultdict(str, context)


def generate_for_lead(lead_id):
    """Create any missing drafts for this lead. Returns the list of types created.

    Existing drafts are replaced. Approved and exported messages are kept.
    """
    lead = db.get_lead(lead_id)
    if lead is None:
        raise ValueError(f"No lead with id {lead_id}")
    config = load_config()
    db.delete_draft_messages(lead_id)
    existing_types = {m["message_type"] for m in db.get_messages_for_lead(lead_id)}
    context = build_context(lead, config)
    created = []
    for message_type in db.MESSAGE_TYPES:
        if message_type in existing_types:
            continue
        content = load_template(message_type).format_map(context)
        db.insert_message(lead_id, message_type, content)
        created.append(message_type)
    if created:
        db.set_lead_status(lead_id, "drafts_generated")
    return created


def main():
    parser = argparse.ArgumentParser(description="Generate outreach drafts.")
    parser.add_argument("lead_id", nargs="?", type=int, help="Lead id to generate drafts for")
    parser.add_argument("--all", action="store_true", help="Generate for every lead with status 'imported'")
    args = parser.parse_args()
    db.init_db()
    if args.all:
        leads = db.get_leads(status="imported")
        if not leads:
            print("No leads with status 'imported'.")
            return
        for lead in leads:
            created = generate_for_lead(lead["id"])
            done = ", ".join(created) if created else "nothing, messages already exist"
            print(f"Lead {lead['id']} ({lead['clinic_name']}): {done}")
    elif args.lead_id:
        created = generate_for_lead(args.lead_id)
        done = ", ".join(created) if created else "nothing, all three messages already exist"
        print(f"Created: {done}")
    else:
        parser.print_usage()


if __name__ == "__main__":
    main()
