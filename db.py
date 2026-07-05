"""SQLite layer for the DigiDental outreach system.

Every script and the app go through these functions. This file makes no
network calls and has no dependencies outside the Python standard library.
All functions are defined here before any other file imports them.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "outreach.db"

LEAD_STATUSES = ("imported", "skipped", "drafts_generated", "reviewed", "exported")

# One outreach message and one follow-up sequence per channel, plus the Loom.
MESSAGE_TYPES = (
    "email_outreach", "email_follow_up",
    "linkedin_outreach", "linkedin_follow_up",
    "instagram_outreach", "instagram_follow_up",
    "facebook_outreach", "facebook_follow_up",
    "loom_script",
)
MESSAGE_STATUSES = ("draft", "approved", "exported")

# Recorded by hand after sending, so the Results page can show what works.
LEAD_OUTCOMES = ("no_reply", "replied", "call_booked", "closed_won", "not_interested")
OUTREACH_CHANNELS = ("email", "linkedin", "instagram", "facebook", "other")

LEAD_INSERT_COLUMNS = (
    "clinic_name", "owner_first_name", "website", "location", "phone", "email",
    "source", "notes", "evening_or_saturday_hours", "single_location",
    "has_chatbot", "mentions_emergency_or_same_day", "review_count",
    "has_after_hours_number", "already_has_ai_receptionist",
    "intent_score", "status",
)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clinic_name TEXT NOT NULL,
            owner_first_name TEXT DEFAULT '',
            website TEXT DEFAULT '',
            location TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            source TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            evening_or_saturday_hours TEXT DEFAULT '',
            single_location TEXT DEFAULT '',
            has_chatbot TEXT DEFAULT '',
            mentions_emergency_or_same_day TEXT DEFAULT '',
            review_count INTEGER DEFAULT 0,
            has_after_hours_number TEXT DEFAULT '',
            already_has_ai_receptionist TEXT DEFAULT '',
            intent_score INTEGER DEFAULT 0,
            enrichment_summary TEXT DEFAULT '',
            enrichment_angle TEXT DEFAULT '',
            status TEXT DEFAULT 'imported',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL REFERENCES leads(id),
            message_type TEXT NOT NULL,
            content_generated TEXT DEFAULT '',
            content_edited TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    existing_columns = [row["name"] for row in conn.execute("PRAGMA table_info(leads)")]
    if "outcome" not in existing_columns:
        conn.execute("ALTER TABLE leads ADD COLUMN outcome TEXT DEFAULT ''")
    if "outcome_channel" not in existing_columns:
        conn.execute("ALTER TABLE leads ADD COLUMN outcome_channel TEXT DEFAULT ''")
    # Messages created before the channel system map onto the email channel.
    conn.execute(
        "UPDATE messages SET message_type = 'email_outreach' "
        "WHERE message_type = 'first_contact'"
    )
    conn.execute(
        "UPDATE messages SET message_type = 'email_follow_up' "
        "WHERE message_type = 'follow_up'"
    )
    conn.commit()
    conn.close()


def insert_lead(fields):
    """Insert a lead. `fields` is a dict with keys from LEAD_INSERT_COLUMNS."""
    values = [fields.get(col, "") for col in LEAD_INSERT_COLUMNS]
    placeholders = ", ".join("?" for _ in LEAD_INSERT_COLUMNS)
    columns = ", ".join(LEAD_INSERT_COLUMNS)
    stamp = now_iso()
    conn = get_conn()
    cur = conn.execute(
        f"INSERT INTO leads ({columns}, created_at, updated_at) "
        f"VALUES ({placeholders}, ?, ?)",
        values + [stamp, stamp],
    )
    conn.commit()
    lead_id = cur.lastrowid
    conn.close()
    return lead_id


def lead_exists(clinic_name, location):
    """True if a lead with the same clinic name and location is already stored."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM leads "
        "WHERE lower(clinic_name) = lower(?) AND lower(location) = lower(?)",
        ((clinic_name or "").strip(), (location or "").strip()),
    ).fetchone()
    conn.close()
    return row is not None


def get_leads(status=None):
    """All leads, hottest first. Optionally filtered to one status."""
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM leads WHERE status = ? "
            "ORDER BY intent_score DESC, clinic_name",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY intent_score DESC, clinic_name"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead(lead_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_lead_status(lead_id, status):
    conn = get_conn()
    conn.execute(
        "UPDATE leads SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), lead_id),
    )
    conn.commit()
    conn.close()


def set_lead_outcome(lead_id, outcome, channel=""):
    conn = get_conn()
    conn.execute(
        "UPDATE leads SET outcome = ?, outcome_channel = ?, updated_at = ? WHERE id = ?",
        (outcome, channel, now_iso(), lead_id),
    )
    conn.commit()
    conn.close()


def set_lead_enrichment(lead_id, summary, angle):
    conn = get_conn()
    conn.execute(
        "UPDATE leads SET enrichment_summary = ?, enrichment_angle = ?, "
        "updated_at = ? WHERE id = ?",
        (summary, angle, now_iso(), lead_id),
    )
    conn.commit()
    conn.close()


def insert_message(lead_id, message_type, content):
    stamp = now_iso()
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO messages "
        "(lead_id, message_type, content_generated, status, created_at, updated_at) "
        "VALUES (?, ?, ?, 'draft', ?, ?)",
        (lead_id, message_type, content, stamp, stamp),
    )
    conn.commit()
    message_id = cur.lastrowid
    conn.close()
    return message_id


def get_messages_for_lead(lead_id):
    """Messages for one lead, always in MESSAGE_TYPES order."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE lead_id = ?", (lead_id,)
    ).fetchall()
    conn.close()
    messages = [dict(r) for r in rows]
    order = {t: i for i, t in enumerate(MESSAGE_TYPES)}
    messages.sort(key=lambda m: order.get(m["message_type"], len(MESSAGE_TYPES)))
    return messages


def delete_draft_messages(lead_id):
    """Remove drafts only. Approved and exported messages are never deleted."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM messages WHERE lead_id = ? AND status = 'draft'", (lead_id,)
    )
    conn.commit()
    conn.close()


def update_message_content(message_id, content_edited):
    conn = get_conn()
    conn.execute(
        "UPDATE messages SET content_edited = ?, updated_at = ? WHERE id = ?",
        (content_edited, now_iso(), message_id),
    )
    conn.commit()
    conn.close()


def set_message_status(message_id, status):
    conn = get_conn()
    conn.execute(
        "UPDATE messages SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), message_id),
    )
    conn.commit()
    conn.close()


def count_approved_messages(lead_id):
    """How many message types for this lead are approved."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(DISTINCT message_type) AS n FROM messages "
        "WHERE lead_id = ? AND status = 'approved'",
        (lead_id,),
    ).fetchone()
    conn.close()
    return row["n"]


def get_export_ready_leads():
    """Leads with at least one approved message, hottest first.

    You rarely use every channel for every lead, so one approved
    message is enough to export.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT l.* FROM leads l "
        "JOIN messages m ON m.lead_id = l.id AND m.status = 'approved' "
        "GROUP BY l.id "
        "ORDER BY l.intent_score DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sent_message_stats():
    """Per message type: how many were exported, and the outcomes of their leads.

    Used by the Results page and the learning batch. An exported message
    counts as sent. Outcomes live on the lead, channel on outcome_channel.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT m.message_type, l.outcome, l.outcome_channel, COUNT(*) AS n "
        "FROM messages m JOIN leads l ON l.id = m.lead_id "
        "WHERE m.status = 'exported' "
        "GROUP BY m.message_type, l.outcome, l.outcome_channel"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
