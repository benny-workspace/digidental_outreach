"""Intelligent header auto-detection for messy real-world CSVs.

Given the headers and a few sample rows, propose a mapping from each CSV
column to a canonical lead field, with a confidence score and a plain
reason. The app shows this for review before anything is imported.

How it maps: each header is normalized and split into word tokens. Each
field scores by how many of the header's tokens match its keyword set.
Generic qualifier words (business, company, contact, lead) carry little
weight; specific field words (location, email, phone, linkedin) carry
full weight. So "location_business" and "business_location" both resolve
to Location, and Apollo, Apify, and Instantly compound headers map
correctly without listing every exact variant.

No network calls, no model. Deterministic and fast.
"""

import difflib
import re

# Canonical fields a column can map to. Order here is also the display order
# and the tiebreak priority (earlier wins an exact score tie).
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

# Whole-phrase synonyms. An exact normalized match here is highest confidence.
# Compound and single-source headers still work through token scoring below,
# so this list only needs the common exact phrases.
FIELD_SYNONYMS = {
    "business_name": [
        "business name", "business", "company", "company name", "practice",
        "practice name", "clinic", "clinic name", "organization", "organisation",
        "organization name", "account name", "title", "name",
        "company name for emails",
    ],
    "first_name": ["first name", "fname", "given name", "forename", "firstname"],
    "last_name": ["last name", "surname", "family name", "lname", "lastname"],
    "contact_name": ["contact", "contact name", "full name", "owner", "owner name", "person", "person name"],
    "owner_first_name": ["owner first name"],
    "role_title": ["role", "job title", "position", "designation", "seniority"],
    "email": ["email", "e mail", "work email", "email address", "emails 0", "contact email", "primary email"],
    "phone": ["phone", "phone number", "mobile", "cell", "telephone", "tel",
              "contact number", "phoneunformatted", "corporate phone", "mobile phone"],
    "website": ["website", "site", "url", "website url", "web", "domain", "homepage", "web address"],
    "location": ["location", "city", "town", "address", "country", "state", "region",
                 "area", "full address", "company city", "company country", "business location"],
    "industry": ["industry", "sector", "category", "categoryname", "business type", "vertical"],
    "niche": ["niche", "specialty", "speciality", "services", "service", "subcategory", "keywords"],
    "notes": ["notes", "note", "observations", "custom notes", "comments", "description",
              "remarks", "personalization", "bio"],
    "source": ["source", "lead source", "origin", "found on", "platform", "list"],
    "review_count": ["review count", "reviews", "reviewscount", "google reviews",
                     "num reviews", "reviews count", "total reviews"],
    "instagram": ["instagram", "insta", "ig", "instagram url", "instagram handle"],
    "facebook": ["facebook", "fb", "facebook url", "facebook page", "facebookprofiles 0", "meta"],
    "linkedin": ["linkedin", "linkedin url", "linkedin profile", "person linkedin url", "linkedin bio"],
    "tiktok": ["tiktok", "tik tok", "tiktok url"],
    "whatsapp": ["whatsapp", "whats app", "whatsapp number", "wa number"],
    "evening_or_saturday_hours": ["evening or saturday hours", "evening hours", "saturday hours", "weekend hours"],
    "single_location": ["single location", "one location"],
    "has_chatbot": ["has chatbot", "chatbot", "live chat", "has live chat"],
    "mentions_emergency_or_same_day": ["mentions emergency or same day", "emergency", "same day"],
    "has_after_hours_number": ["has after hours number", "after hours number", "after hours line"],
    "already_has_ai_receptionist": ["already has ai receptionist", "ai receptionist", "has ai"],
}

# Specific tokens that strongly identify one field. Full weight.
FIELD_ESSENCE = {
    "business_name": ["practice", "clinic", "dental", "dentist", "brand", "shop",
                      "store", "firm", "restaurant", "salon", "gym", "agency", "studio"],
    "first_name": ["first", "fname", "given", "forename", "firstname"],
    "last_name": ["last", "surname", "family", "lname", "lastname"],
    "contact_name": ["owner", "fullname"],
    "role_title": ["role", "job", "position", "designation", "seniority"],
    "email": ["email", "emails", "mail"],
    "phone": ["phone", "phones", "mobile", "cell", "telephone", "tel", "phoneunformatted"],
    "website": ["website", "site", "web", "domain", "homepage"],
    "location": ["location", "city", "town", "address", "country", "state", "region", "area"],
    "industry": ["industry", "sector", "category", "categoryname", "vertical"],
    "niche": ["niche", "specialty", "speciality", "services", "service", "keywords"],
    "notes": ["notes", "note", "observations", "comments", "description",
              "remarks", "personalization", "bio"],
    "source": ["source", "origin"],
    "review_count": ["reviews", "reviewscount"],
    "instagram": ["instagram", "insta", "instagrams"],
    "facebook": ["facebook", "fb", "facebookprofiles", "facebooks"],
    "linkedin": ["linkedin", "linkedins"],
    "tiktok": ["tiktok", "tiktoks"],
    "whatsapp": ["whatsapp"],
    "evening_or_saturday_hours": ["evening", "saturday", "weekend"],
    "single_location": [],
    "has_chatbot": ["chatbot"],
    "mentions_emergency_or_same_day": ["emergency"],
    "has_after_hours_number": [],
    "already_has_ai_receptionist": ["receptionist"],
}

# Words that qualify a field but do not identify it. Low weight, so a header
# that also contains a specific field word resolves to that field.
GENERIC_TOKENS = {
    "business", "company", "companies", "corporate", "org", "organization",
    "organisation", "account", "contact", "lead", "prospect", "client", "person",
    "people", "primary", "main", "work", "personal", "info", "information", "data",
    "details", "custom", "variable", "field", "value", "number", "num", "no", "url",
    "link", "profile", "page", "handle", "name", "the", "of", "for", "my", "full",
    "0", "1", "2", "id",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^(https?://|www\.)\S+|.+\.(com|net|org|io|co|dental|dentist)\b", re.IGNORECASE)
PHONE_RE = re.compile(r"^[\d\s()+.\-]{7,20}$")

LOW_CONFIDENCE = 0.7


def normalize_header(header):
    text = (header or "").strip().lower()
    text = re.sub(r"[_\-./\\]+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize(normalized):
    return [t for t in normalized.split() if t]


# Precompute the token set for each field: essence tokens plus every token
# appearing in its synonym phrases.
def _build_field_tokens():
    field_tokens = {}
    for field in CANONICAL_FIELDS:
        tokens = set(FIELD_ESSENCE.get(field, []))
        for phrase in FIELD_SYNONYMS.get(field, []):
            tokens.update(_tokenize(normalize_header(phrase)))
        field_tokens[field] = tokens
    return field_tokens


FIELD_TOKENS = _build_field_tokens()


def _exact_synonym(normalized):
    """Whole-phrase exact match against the synonym table. Highest confidence."""
    if normalized in CANONICAL_FIELDS:
        return normalized, 1.0, "exact field name"
    for field in CANONICAL_FIELDS:
        if normalized in FIELD_SYNONYMS.get(field, []):
            return field, 0.95, "known synonym"
    return None


def _token_score(normalized):
    """Score every field by weighted token overlap. Returns best (field, conf, reason)."""
    tokens = _tokenize(normalized)
    if not tokens:
        return None
    scores = {}
    matched_word = {}
    for field in CANONICAL_FIELDS:
        field_tokens = FIELD_TOKENS[field]
        total = 0.0
        hit = None
        for token in tokens:
            if token in field_tokens:
                weight = 0.15 if token in GENERIC_TOKENS else 1.0
                total += weight
                if weight >= 1.0 and hit is None:
                    hit = token
        if total > 0:
            scores[field] = total
            matched_word[field] = hit
    if not scores:
        return None
    # Highest score wins; ties break by CANONICAL_FIELDS order (priority).
    best_field = max(CANONICAL_FIELDS, key=lambda f: (scores.get(f, 0.0), -CANONICAL_FIELDS.index(f)))
    best = scores[best_field]
    ordered = sorted(scores.values(), reverse=True)
    second = ordered[1] if len(ordered) > 1 else 0.0
    word = matched_word.get(best_field)
    if best >= 1.0:
        confidence = 0.9 if (best - second) >= 0.5 else 0.82
        reason = f"matched on '{word}'" if word else "matched on keywords"
    else:
        confidence = 0.75
        reason = "matched on a general keyword"
    return best_field, confidence, reason


def _synonym_match(normalized):
    """Best (field, confidence, reason) from headers, or None."""
    exact = _exact_synonym(normalized)
    if exact is not None:
        return exact
    scored = _token_score(normalized)
    if scored is not None:
        return scored
    # Last resort: fuzzy match against synonym phrases for typos.
    candidates = []
    for field in CANONICAL_FIELDS:
        close = difflib.get_close_matches(normalized, FIELD_SYNONYMS.get(field, []), n=1, cutoff=0.85)
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


STRONG_BUSINESS_WORDS = {
    "company", "company name", "organization", "organisation", "organization name",
    "business", "business name", "account name", "practice", "practice name",
    "clinic", "clinic name",
}


def _disambiguate_title(proposals):
    """`title` means job title when a real company column is also present.

    Apify Google Maps has a `title` (the business) and no company column,
    so title stays business_name. Apollo has both `Title` (job) and
    `Company`, so title becomes role_title and Company keeps business_name.
    """
    norms = {id(p): normalize_header(p["header"]) for p in proposals}
    has_business_col = any(norms[id(p)] in STRONG_BUSINESS_WORDS for p in proposals)
    role_taken = any(p["field"] == "role_title" for p in proposals)
    if has_business_col and not role_taken:
        for p in proposals:
            if norms[id(p)] == "title" and p["field"] == "business_name":
                p["field"] = "role_title"
                p["confidence"] = 0.8
                p["reason"] = "job title (a company column is also present)"


def detect_mapping(headers, sample_rows):
    """Propose a mapping for every header.

    Returns a list of dicts, one per header, in order:
        {"header", "field" (or None), "confidence", "reason"}
    Duplicate targets keep the highest-confidence column; the loser is
    unmapped with a reason, so the user can resolve it by hand.
    """
    proposals = []
    for index, header in enumerate(headers):
        # Two-plus levels of nesting (a/b/c) marks an export sub-property,
        # like instagramProfiles/0/followersCount. Never a lead field.
        if (header or "").count("/") + (header or "").count("\\") >= 2:
            proposals.append({"header": header, "field": None,
                              "confidence": 0.0, "reason": "nested sub-column, kept as raw data"})
            continue
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

    _disambiguate_title(proposals)

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
