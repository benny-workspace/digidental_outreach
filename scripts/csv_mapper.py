"""Header auto-detection for messy real-world CSVs.

Given the headers and a few sample rows, propose a mapping from each CSV
column to a canonical lead field, with a confidence score and a plain
reason. The app shows this for review before anything is imported.

No network calls, no model. Deterministic and fast.
"""

import difflib
import re

# Canonical fields a column can map to. Order matters for display.
CANONICAL_FIELDS = (
    "business_name", "first_name", "last_name", "contact_name", "role_title",
    "email", "phone", "website", "location", "industry", "niche", "notes",
    "source", "review_count",
    "instagram", "facebook", "linkedin", "tiktok", "whatsapp",
    "evening_or_saturday_hours", "single_location", "has_chatbot",
    "mentions_emergency_or_same_day", "has_after_hours_number",
    "already_has_ai_receptionist", "owner_first_name",
)

SOCIAL_FIELDS = ("instagram", "facebook", "linkedin", "tiktok", "whatsapp")

FIELD_SYNONYMS = {
    "business_name": [
        "business name", "business", "company", "company name", "practice",
        "practice name", "clinic", "clinic name", "organization",
        "organisation", "account name", "title", "categoryname", "name",
    ],
    "first_name": ["first name", "fname", "given name", "forename"],
    "last_name": ["last name", "surname", "family name", "lname"],
    "contact_name": ["contact", "contact name", "full name", "owner", "owner name", "person"],
    "owner_first_name": ["owner first name"],
    "role_title": ["role", "title", "job title", "position", "designation"],
    "email": ["email", "e mail", "work email", "email address", "emails 0", "contact email"],
    "phone": ["phone", "phone number", "mobile", "cell", "telephone", "tel", "contact number", "phoneunformatted"],
    "website": ["website", "site", "url", "website url", "web", "domain", "homepage"],
    "location": ["location", "city", "town", "address", "country", "state", "region", "area", "full address"],
    "industry": ["industry", "sector", "category", "categoryname", "business type"],
    "niche": ["niche", "specialty", "speciality", "services", "service", "subcategory"],
    "notes": ["notes", "note", "observations", "custom notes", "comments", "description", "remarks"],
    "source": ["source", "lead source", "origin", "found on", "platform"],
    "review_count": ["review count", "reviews", "reviewscount", "google reviews", "num reviews", "reviews count"],
    "instagram": ["instagram", "insta", "ig", "instagram url", "instagram handle"],
    "facebook": ["facebook", "fb", "facebook url", "facebook page", "facebookprofiles 0"],
    "linkedin": ["linkedin", "linkedin url", "linkedin profile"],
    "tiktok": ["tiktok", "tik tok", "tiktok url"],
    "whatsapp": ["whatsapp", "whats app", "whatsapp number"],
    "evening_or_saturday_hours": ["evening or saturday hours", "evening hours", "saturday hours", "weekend hours"],
    "single_location": ["single location", "one location", "locations"],
    "has_chatbot": ["has chatbot", "chatbot", "live chat", "has live chat"],
    "mentions_emergency_or_same_day": ["mentions emergency or same day", "emergency", "same day"],
    "has_after_hours_number": ["has after hours number", "after hours number", "after hours line"],
    "already_has_ai_receptionist": ["already has ai receptionist", "ai receptionist", "has ai"],
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^(https?://|www\.)\S+|.+\.(com|net|org|io|co|dental|dentist)\b", re.IGNORECASE)
PHONE_RE = re.compile(r"^[\d\s()+.\-]{7,20}$")

LOW_CONFIDENCE = 0.7


def normalize_header(header):
    text = (header or "").strip().lower()
    text = re.sub(r"[_\-./\\]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _synonym_match(normalized):
    """Best (field, confidence, reason) from the synonym table, or None."""
    if normalized in CANONICAL_FIELDS:
        return normalized, 1.0, "exact field name"
    for field, synonyms in FIELD_SYNONYMS.items():
        if normalized in synonyms:
            return field, 0.95, "known synonym"
    for field, synonyms in FIELD_SYNONYMS.items():
        for synonym in synonyms:
            if len(synonym) >= 4 and (normalized.startswith(synonym) or synonym in normalized.split()):
                return field, 0.8, f"contains '{synonym}'"
    candidates = []
    for field, synonyms in FIELD_SYNONYMS.items():
        close = difflib.get_close_matches(normalized, synonyms, n=1, cutoff=0.85)
        if close:
            candidates.append((field, close[0]))
    if candidates:
        field, matched = candidates[0]
        return field, 0.7, f"close to '{matched}'"
    return None


def _value_match(samples):
    """Infer a field from sample cell values when the header says nothing."""
    values = [str(v).strip() for v in samples if str(v or "").strip()]
    if not values:
        return None
    if all(EMAIL_RE.match(v) for v in values):
        return "email", 0.65, "values look like emails"
    if all(URL_RE.match(v) for v in values):
        socials = {
            "instagram.com": "instagram", "facebook.com": "facebook",
            "linkedin.com": "linkedin", "tiktok.com": "tiktok",
        }
        for domain, field in socials.items():
            if all(domain in v.lower() for v in values):
                return field, 0.65, f"values are {field} links"
        return "website", 0.6, "values look like URLs"
    if all(PHONE_RE.match(v) for v in values):
        return "phone", 0.55, "values look like phone numbers"
    return None


def detect_mapping(headers, sample_rows):
    """Propose a mapping for every header.

    Returns a list of dicts, one per header, in order:
        {"header", "field" (or None), "confidence", "reason"}
    Duplicate targets keep the highest-confidence column; the loser is
    unmapped with a reason, so the user can resolve it by hand.
    """
    proposals = []
    for index, header in enumerate(headers):
        normalized = normalize_header(header)
        match = _synonym_match(normalized)
        if match is None:
            samples = [row[index] for row in sample_rows if index < len(row)][:5]
            match = _value_match(samples)
        if match is None:
            proposals.append({"header": header, "field": None,
                              "confidence": 0.0, "reason": "no match, kept as raw data"})
        else:
            field, confidence, reason = match
            proposals.append({"header": header, "field": field,
                              "confidence": confidence, "reason": reason})

    best_for_field = {}
    for proposal in proposals:
        field = proposal["field"]
        if field is None:
            continue
        current = best_for_field.get(field)
        if current is None or proposal["confidence"] > current["confidence"]:
            best_for_field[field] = proposal
    for proposal in proposals:
        field = proposal["field"]
        if field is not None and best_for_field[field] is not proposal:
            winner = best_for_field[field]["header"]
            proposal["field"] = None
            proposal["confidence"] = 0.0
            proposal["reason"] = f"duplicate of '{winner}', kept as raw data"
    return proposals


def mapping_to_dict(proposals):
    """{csv_header: canonical_field} for the confirmed mapping."""
    return {p["header"]: p["field"] for p in proposals if p["field"]}
