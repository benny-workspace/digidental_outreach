"""SQLite layer for the outreach system.

Every script and the app go through these functions. This file makes no
network calls. All functions are defined here before any other file
imports them. Data is tenant-aware: every row carries a tenant_id so the
same product can later serve other businesses. The active tenant comes
from config.yaml plus optional config.local.yaml (key: tenant), default
`default`.
"""

import json
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
OUTREACH_TYPES = (
    "email_outreach", "linkedin_outreach",
    "instagram_outreach", "facebook_outreach",
)
MESSAGE_STATUSES = ("draft", "approved", "exported")

# Copy variants for outreach messages. "direct" is the base template.
VARIANTS = ("direct", "short", "curiosity", "objection_aware")

# Legacy per-lead outcomes, kept so old data keeps working.
LEAD_OUTCOMES = ("no_reply", "replied", "call_booked", "closed_won", "not_interested")
OUTREACH_CHANNELS = ("email", "linkedin", "instagram", "facebook", "other")

# Detailed outcomes for the outreach log.
OUTCOME_OPTIONS = (
    "no_reply", "opened_only", "replied_positive", "replied_neutral",
    "replied_negative", "booked_call", "closed_won", "closed_lost",
    "not_interested", "wrong_contact", "follow_up_later",
)
POSITIVE_OUTCOMES = {"replied_positive", "booked_call", "closed_won"}
LEGACY_POSITIVE_OUTCOMES = {"replied", "call_booked", "closed_won"}
REPLY_QUALITIES = ("", "good", "neutral", "bad")
OBJECTION_TYPES = (
    "", "already has receptionist", "price", "scam fear", "too small",
    "ai distrust", "timing", "other",
)
CONVERSION_STAGES = (
    "", "contacted", "replied", "call_booked", "proposal",
    "closed_won", "closed_lost",
)

_active_tenant = None


def active_tenant():
    """Tenant this app instance works with. Cached after config load."""
    global _active_tenant
    if _active_tenant is None:
        tenant = "default"
        try:
            import app_config
            tenant = str(app_config.get_config_value("tenant", "default"))
        except Exception:
            pass
        _active_tenant = tenant or "default"
    return _active_tenant


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(conn, table, columns):
    """Add any missing columns. Safe to run every start."""
    existing = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


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

        CREATE TABLE IF NOT EXISTS import_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT DEFAULT 'default',
            source_file TEXT DEFAULT '',
            mapping TEXT DEFAULT '{}',
            rows_imported INTEGER DEFAULT 0,
            rows_disqualified INTEGER DEFAULT 0,
            rows_duplicate INTEGER DEFAULT 0,
            warnings TEXT DEFAULT '[]',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS outreach_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT DEFAULT 'default',
            lead_id INTEGER NOT NULL REFERENCES leads(id),
            channel TEXT DEFAULT '',
            message_type TEXT DEFAULT '',
            variant TEXT DEFAULT 'direct',
            outcome TEXT DEFAULT '',
            reply_quality TEXT DEFAULT '',
            meeting_booked INTEGER DEFAULT 0,
            objection_type TEXT DEFAULT '',
            conversion_stage TEXT DEFAULT '',
            rating INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            synced INTEGER DEFAULT 0,
            created_at TEXT
        );
        """
    )
    _ensure_columns(conn, "leads", {
        "outcome": "TEXT DEFAULT ''",
        "outcome_channel": "TEXT DEFAULT ''",
        "tenant_id": "TEXT DEFAULT 'default'",
        "first_name": "TEXT DEFAULT ''",
        "last_name": "TEXT DEFAULT ''",
        "role_title": "TEXT DEFAULT ''",
        "industry": "TEXT DEFAULT ''",
        "niche": "TEXT DEFAULT ''",
        "social_links": "TEXT DEFAULT '{}'",
        "raw_columns": "TEXT DEFAULT '{}'",
        "import_batch_id": "INTEGER",
        "source_file": "TEXT DEFAULT ''",
        "last_outreach_channel": "TEXT DEFAULT ''",
        "last_outreach_date": "TEXT DEFAULT ''",
        "outcome_notes": "TEXT DEFAULT ''",
    })
    _ensure_columns(conn, "messages", {
        "tenant_id": "TEXT DEFAULT 'default'",
        "variant": "TEXT DEFAULT 'direct'",
    })
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


# -------------------------------------------------------------------- Backups

BACKUP_DIR = DATA_DIR / "backups"
BACKUP_KEEP = 30


def backup_db(tag="manual"):
    """Snapshot the whole database into data/backups. Returns the new path.

    Uses SQLite's online backup API, so the copy is consistent even if
    the app writes at the same moment. The filename starts with a
    timestamp, so name order is age order.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = BACKUP_DIR / f"outreach_{stamp}_{tag}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    _prune_backups()
    return target


def auto_backup():
    """Daily safety net, called on every app rerun. Costs one directory
    check when today's backup already exists."""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    if any(BACKUP_DIR.glob(f"outreach_{today}_*.db")):
        return None
    return backup_db(tag="auto")


def list_backups():
    """Backups newest first, as dicts with path, name, size, modified."""
    if not BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(BACKUP_DIR.glob("outreach_*.db"), reverse=True):
        stat = f.stat()
        out.append({
            "path": f, "name": f.name, "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return out


def _prune_backups():
    files = sorted(BACKUP_DIR.glob("outreach_*.db"))
    for old in files[:-BACKUP_KEEP]:
        old.unlink()


def restore_backup(backup_path):
    """Replace the live database with a backup, in place.

    The current database is backed up first (tag pre_restore), so a
    restore is always reversible. Writing through the backup API instead
    of copying the file avoids Windows file locks from open connections.
    """
    backup_path = Path(backup_path)
    if not backup_path.exists():
        raise FileNotFoundError(backup_path)
    backup_db(tag="pre_restore")
    src = sqlite3.connect(backup_path)
    dst = sqlite3.connect(DB_PATH)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()


LEAD_INSERT_COLUMNS = (
    "tenant_id", "clinic_name", "owner_first_name", "first_name", "last_name",
    "role_title", "industry", "niche", "website", "location", "phone", "email",
    "social_links", "source", "notes", "raw_columns", "import_batch_id",
    "source_file", "evening_or_saturday_hours", "single_location",
    "has_chatbot", "mentions_emergency_or_same_day", "review_count",
    "has_after_hours_number", "already_has_ai_receptionist",
    "intent_score", "status",
)

LEAD_EDITABLE_COLUMNS = (
    "owner_first_name", "first_name", "last_name", "role_title", "industry",
    "niche", "website", "location", "phone", "email", "notes", "social_links",
    "evening_or_saturday_hours", "single_location", "has_chatbot",
    "mentions_emergency_or_same_day", "review_count",
    "has_after_hours_number", "already_has_ai_receptionist",
    "intent_score", "status", "outcome", "outcome_channel", "outcome_notes",
    "last_outreach_channel", "last_outreach_date",
)


def insert_lead(fields):
    """Insert a lead. `fields` is a dict with keys from LEAD_INSERT_COLUMNS."""
    fields = dict(fields)
    fields.setdefault("tenant_id", active_tenant())
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


def update_lead_fields(lead_id, fields):
    """Update a lead. Only columns in LEAD_EDITABLE_COLUMNS are accepted."""
    updates = {k: v for k, v in fields.items() if k in LEAD_EDITABLE_COLUMNS}
    if not updates:
        return
    assignments = ", ".join(f"{col} = ?" for col in updates)
    conn = get_conn()
    conn.execute(
        f"UPDATE leads SET {assignments}, updated_at = ? WHERE id = ?",
        list(updates.values()) + [now_iso(), lead_id],
    )
    conn.commit()
    conn.close()


def delete_leads(lead_ids):
    """Permanently delete leads plus their messages and outcome logs."""
    ids = [int(i) for i in lead_ids]
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    conn = get_conn()
    conn.execute(f"DELETE FROM messages WHERE lead_id IN ({marks})", ids)
    conn.execute(f"DELETE FROM outreach_log WHERE lead_id IN ({marks})", ids)
    cur = conn.execute(f"DELETE FROM leads WHERE id IN ({marks})", ids)
    conn.commit()
    conn.close()
    return cur.rowcount


def lead_exists(clinic_name, location):
    """True if a lead with the same business name and location is already stored."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM leads WHERE tenant_id = ? "
        "AND lower(clinic_name) = lower(?) AND lower(location) = lower(?)",
        (active_tenant(), (clinic_name or "").strip(), (location or "").strip()),
    ).fetchone()
    conn.close()
    return row is not None


def get_leads(status=None):
    """All leads for the active tenant, hottest first."""
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM leads WHERE tenant_id = ? AND status = ? "
            "ORDER BY intent_score DESC, clinic_name",
            (active_tenant(), status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM leads WHERE tenant_id = ? "
            "ORDER BY intent_score DESC, clinic_name",
            (active_tenant(),),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead(lead_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def set_lead_status(lead_id, status):
    update_lead_fields(lead_id, {"status": status})


def set_lead_outcome(lead_id, outcome, channel=""):
    update_lead_fields(lead_id, {"outcome": outcome, "outcome_channel": channel})


def set_lead_enrichment(lead_id, summary, angle):
    conn = get_conn()
    conn.execute(
        "UPDATE leads SET enrichment_summary = ?, enrichment_angle = ?, "
        "updated_at = ? WHERE id = ?",
        (summary, angle, now_iso(), lead_id),
    )
    conn.commit()
    conn.close()


def create_import_batch(source_file, mapping, summary):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO import_batches "
        "(tenant_id, source_file, mapping, rows_imported, rows_disqualified, "
        "rows_duplicate, warnings, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            active_tenant(), source_file, json.dumps(mapping),
            summary.get("imported", 0), summary.get("disqualified", 0),
            summary.get("duplicates", 0), json.dumps(summary.get("errors", [])),
            now_iso(),
        ),
    )
    conn.commit()
    batch_id = cur.lastrowid
    conn.close()
    return batch_id


def update_import_batch(batch_id, summary):
    """Write the final counts after the rows are actually inserted."""
    conn = get_conn()
    conn.execute(
        "UPDATE import_batches SET rows_imported = ?, rows_disqualified = ?, "
        "rows_duplicate = ?, warnings = ? WHERE id = ?",
        (
            summary.get("imported", 0), summary.get("disqualified", 0),
            summary.get("duplicates", 0), json.dumps(summary.get("errors", [])),
            batch_id,
        ),
    )
    conn.commit()
    conn.close()


def get_import_batches():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM import_batches WHERE tenant_id = ? ORDER BY id DESC",
        (active_tenant(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_message(lead_id, message_type, content, variant="direct"):
    stamp = now_iso()
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO messages "
        "(tenant_id, lead_id, message_type, variant, content_generated, "
        "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)",
        (active_tenant(), lead_id, message_type, variant, content, stamp, stamp),
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


def delete_draft_messages(lead_id, message_type=None):
    """Remove drafts only. Approved and exported messages are never deleted.

    Pass message_type to clear just one channel's draft, so regenerating
    one channel never resets the others.
    """
    conn = get_conn()
    if message_type:
        conn.execute(
            "DELETE FROM messages WHERE lead_id = ? AND status = 'draft' "
            "AND message_type = ?",
            (lead_id, message_type),
        )
    else:
        conn.execute(
            "DELETE FROM messages WHERE lead_id = ? AND status = 'draft'",
            (lead_id,),
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
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(DISTINCT message_type) AS n FROM messages "
        "WHERE lead_id = ? AND status = 'approved'",
        (lead_id,),
    ).fetchone()
    conn.close()
    return row["n"]


def get_export_ready_leads():
    """Leads with at least one approved message, hottest first."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT l.* FROM leads l "
        "JOIN messages m ON m.lead_id = l.id AND m.status = 'approved' "
        "WHERE l.tenant_id = ? "
        "GROUP BY l.id ORDER BY l.intent_score DESC",
        (active_tenant(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_outreach(fields):
    """Record one outreach result. Also updates the lead's quick-view fields."""
    stamp = now_iso()
    conn = get_conn()
    conn.execute(
        "INSERT INTO outreach_log "
        "(tenant_id, lead_id, channel, message_type, variant, outcome, "
        "reply_quality, meeting_booked, objection_type, conversion_stage, "
        "rating, notes, synced, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
        (
            active_tenant(), fields["lead_id"], fields.get("channel", ""),
            fields.get("message_type", ""), fields.get("variant", "direct"),
            fields.get("outcome", ""), fields.get("reply_quality", ""),
            1 if fields.get("meeting_booked") else 0,
            fields.get("objection_type", ""), fields.get("conversion_stage", ""),
            int(fields.get("rating", 0) or 0), fields.get("notes", ""), stamp,
        ),
    )
    conn.commit()
    conn.close()
    legacy = {
        "replied_positive": "replied", "replied_neutral": "replied",
        "replied_negative": "replied", "booked_call": "call_booked",
        "closed_won": "closed_won", "not_interested": "not_interested",
    }.get(fields.get("outcome", ""), "no_reply")
    update_lead_fields(fields["lead_id"], {
        "outcome": legacy,
        "outcome_channel": fields.get("channel", ""),
        "outcome_notes": fields.get("notes", ""),
        "last_outreach_channel": fields.get("channel", ""),
        "last_outreach_date": stamp,
    })


def get_outreach_logs():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM outreach_log WHERE tenant_id = ? ORDER BY id DESC",
        (active_tenant(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_unsynced_logs():
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM outreach_log WHERE tenant_id = ? AND synced = 0",
        (active_tenant(),),
    ).fetchone()
    conn.close()
    return row["n"]


def mark_logs_synced():
    conn = get_conn()
    conn.execute(
        "UPDATE outreach_log SET synced = 1 WHERE tenant_id = ? AND synced = 0",
        (active_tenant(),),
    )
    conn.commit()
    conn.close()


def variant_stats():
    """Per (message_type, variant): sends and positive outcomes from the log.

    This is the whole learning model: explainable win rates. The ranker in
    generate_drafts turns these into a preferred variant per channel.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT message_type, variant, outcome, COUNT(*) AS n "
        "FROM outreach_log WHERE tenant_id = ? "
        "GROUP BY message_type, variant, outcome",
        (active_tenant(),),
    ).fetchall()
    conn.close()
    stats = {}
    for row in rows:
        key = (row["message_type"], row["variant"] or "direct")
        wins, total = stats.get(key, (0, 0))
        is_win = row["outcome"] in POSITIVE_OUTCOMES
        stats[key] = (wins + (row["n"] if is_win else 0), total + row["n"])
    return stats


def get_sent_message_stats():
    """Kept for the learning batch: exported messages joined with lead outcomes."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT m.message_type, l.outcome, l.outcome_channel, COUNT(*) AS n "
        "FROM messages m JOIN leads l ON l.id = m.lead_id "
        "WHERE m.status = 'exported' AND l.tenant_id = ? "
        "GROUP BY m.message_type, l.outcome, l.outcome_channel",
        (active_tenant(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
