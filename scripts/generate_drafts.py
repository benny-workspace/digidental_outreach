"""Generate outreach drafts for a lead, per channel, with copy variants.

Usage:
    python scripts\\generate_drafts.py 3                  (all channels, auto variants)
    python scripts\\generate_drafts.py 3 --type email_outreach --variant curiosity
    python scripts\\generate_drafts.py --all              (every 'imported' lead)

Plain string substitution against the files in prompts\\. Variants live in
prompts\\variants\\<type>__<variant>.txt and fall back to the base template.
The variant picked by default is the one with the best recorded win rate
for that channel (explainable: wins out of sends, nothing hidden).
No LLM, no network calls, instant.
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

import company
import db

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"
VARIANTS_DIR = PROMPTS_DIR / "variants"

# Deterministic angle rules. Checked in this order.
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


def load_template(message_type, variant="direct"):
    """Variant template if it exists, otherwise the base template."""
    if variant and variant != "direct":
        variant_path = VARIANTS_DIR / f"{message_type}__{variant}.txt"
        if variant_path.exists():
            return variant_path.read_text(encoding="utf-8")
    return (PROMPTS_DIR / f"{message_type}.txt").read_text(encoding="utf-8")


def format_day(d):
    return f"{d.strftime('%B')} {d.day}"


def previous_contact_date(lead_id):
    for message in db.get_messages_for_lead(lead_id):
        if message["message_type"] == "email_outreach" and message["created_at"]:
            try:
                return format_day(datetime.fromisoformat(message["created_at"]).date())
            except ValueError:
                break
    return format_day(date.today())


def angle_rules():
    """Angle copy for the active tenant. The profile's `angles` key wins;
    the built-in set is the DigiDental fallback so nothing ever breaks."""
    profile_angles = company.load_profile().get("angles") or {}
    rules = {}
    for key, fallback in DETERMINISTIC_ANGLES.items():
        merged = dict(fallback)
        merged.update(profile_angles.get(key) or {})
        rules[key] = merged
    return rules


def pick_angles(lead):
    """Deterministic angles by default. Enrichment wins when present."""
    rules = angle_rules()
    if lead["evening_or_saturday_hours"] == "Y":
        angles = dict(rules["evening"])
    elif lead["mentions_emergency_or_same_day"] == "Y":
        angles = dict(rules["emergency"])
    else:
        angles = dict(rules["default"])
    enriched_angle = (lead.get("enrichment_angle") or "").strip()
    if enriched_angle:
        angles["angle_line"] = enriched_angle
        angles["pain_point"] = enriched_angle
    return angles


def best_variant(message_type):
    """(variant, reason) with the best win rate for this channel.

    Laplace-smoothed so one lucky send does not dominate: at least three
    recorded sends before a variant can beat the default.
    """
    stats = db.variant_stats()
    best = ("direct", "default, not enough outcome data yet")
    best_score = 0.0
    for variant in db.VARIANTS:
        wins, total = stats.get((message_type, variant), (0, 0))
        if total < 3:
            continue
        score = (wins + 1) / (total + 2)
        if score > best_score:
            best_score = score
            best = (variant, f"best win rate: {wins} positive of {total} logged sends")
    return best


# --- insertion hygiene: every value is cleaned before it enters copy -------

BUSINESS_SUFFIX_RE = re.compile(
    r"\s*,?\s*(inc\.?|llc\.?|ltd\.?|pllc|p\.?c\.?|corp\.?|co\.)\s*$",
    re.IGNORECASE,
)


def clean_fragment(text):
    """Collapse whitespace and replace dashes the brand rules forbid."""
    text = (text or "").replace("—", ", ").replace("–", ", ")
    return " ".join(text.split()).strip()


def as_sentence(text):
    """A cleaned fragment as a full sentence: ends with punctuation."""
    text = clean_fragment(text)
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text[0].upper() + text[1:]


def first_name_only(value):
    """First token of a name, capitalized. 'maria lopez' becomes 'Maria'."""
    tokens = (value or "").strip().split()
    if not tokens:
        return ""
    name = tokens[0].strip(",.")
    return (name[:1].upper() + name[1:]) if name else ""


def natural_business_name(raw):
    """A copy-friendly business name. The database keeps the full name.

    'Sierra Vista Family Dental Center - Chiricahua Community Health
    Centers, Inc.' reads as 'Sierra Vista Family Dental Center' in a
    message, which is how the owner says it out loud.
    """
    name = clean_fragment(raw)
    for separator in (" - ", " | "):
        head = name.split(separator)[0].strip()
        if len(head.split()) >= 2:
            name = head
    while True:
        stripped = BUSINESS_SUFFIX_RE.sub("", name).strip(" ,")
        if stripped == name or not stripped:
            break
        name = stripped
    return name or clean_fragment(raw)


def polish(content):
    """Final pass over a filled template: no stray spacing artifacts."""
    content = re.sub(r"[ \t]+\n", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip() + "\n"


def build_context(lead, config):
    """All template values, cleaned. defaultdict(str) so a missing key
    renders empty instead of crashing."""
    profile = company.load_profile()
    angles = pick_angles(lead)
    owner = (
        first_name_only(lead.get("owner_first_name"))
        or first_name_only(lead.get("first_name"))
        or "there"
    )
    context = {
        "owner_first_name": owner,
        "clinic_name": natural_business_name(lead["clinic_name"]),
        "founder_name": clean_fragment(profile.get("founder_name") or config.get("founder_name", "")),
        "company_name": clean_fragment(profile.get("company_name", "")),
        "calendar_name": clean_fragment(profile.get("calendar_name") or config.get("calendar_name", "your calendar")),
        "previous_date": previous_contact_date(lead["id"]),
        "angle_line": as_sentence(angles["angle_line"]),
        "pain_point": clean_fragment(angles["pain_point"]).rstrip("."),
        "one_line_value_prop": as_sentence(angles["one_line_value_prop"]),
        "location": clean_fragment(lead.get("location")),
        "niche": clean_fragment(lead.get("niche")),
    }
    return defaultdict(str, context)


def generate_for_lead(lead_id, only_type=None, variant=None):
    """Create drafts for a lead. Returns [(message_type, variant), ...].

    With only_type, regenerates that one channel and leaves the others
    untouched. Without a variant, each outreach channel uses its
    best-performing variant from the outcome history.
    Approved and exported messages are never replaced.
    """
    lead = db.get_lead(lead_id)
    if lead is None:
        raise ValueError(f"No lead with id {lead_id}")
    config = load_config()
    types = [only_type] if only_type else list(db.MESSAGE_TYPES)
    for message_type in types:
        db.delete_draft_messages(lead_id, message_type)
    existing_types = {m["message_type"] for m in db.get_messages_for_lead(lead_id)}
    context = build_context(lead, config)
    created = []
    for message_type in types:
        if message_type in existing_types:
            continue
        if message_type in db.OUTREACH_TYPES:
            chosen = variant or best_variant(message_type)[0]
        else:
            chosen = "direct"
        content = polish(load_template(message_type, chosen).format_map(context))
        db.insert_message(lead_id, message_type, content, variant=chosen)
        created.append((message_type, chosen))
    if created and lead["status"] in ("imported", "skipped"):
        db.set_lead_status(lead_id, "drafts_generated")
    return created


def main():
    parser = argparse.ArgumentParser(description="Generate outreach drafts.")
    parser.add_argument("lead_id", nargs="?", type=int)
    parser.add_argument("--all", action="store_true", help="every lead with status 'imported'")
    parser.add_argument("--type", dest="only_type", choices=db.MESSAGE_TYPES)
    parser.add_argument("--variant", choices=db.VARIANTS)
    args = parser.parse_args()
    db.init_db()
    if args.all:
        leads = db.get_leads(status="imported")
        if not leads:
            print("No leads with status 'imported'.")
            return
        for lead in leads:
            created = generate_for_lead(lead["id"])
            done = ", ".join(f"{t} ({v})" for t, v in created) or "nothing, messages already exist"
            print(f"Lead {lead['id']} ({lead['clinic_name']}): {done}")
    elif args.lead_id:
        created = generate_for_lead(args.lead_id, args.only_type, args.variant)
        done = ", ".join(f"{t} ({v})" for t, v in created) or "nothing to create"
        print(f"Created: {done}")
    else:
        parser.print_usage()


if __name__ == "__main__":
    main()
