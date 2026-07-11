"""Outreach Studio. A local outreach system that runs with Streamlit.

This file never calls Ollama and never makes a network request. Enrichment,
the learning batch, and the planner sync are separate command line scripts.

Pages are tenant-aware. Business specifics come from the active workspace
profile (company.py), not from this code, so the same app serves any tenant.
"""

import json
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

import streamlit as st

import company
import csv_mapper
import db
import export as export_script
import generate_drafts
import import_leads

db.init_db()

_page_icon = BASE_DIR / "assets" / "logo_transparent.png"
st.set_page_config(
    page_title="Outreach Studio", layout="wide",
    page_icon=str(_page_icon) if _page_icon.exists() else None,
    initial_sidebar_state="expanded",
)

# Minimal look: hide Streamlit chrome, tighten spacing, soften panels.
# Hide only the Deploy button, main menu, and footer. Never hide the whole
# header or toolbar: the sidebar open/close arrow lives there, and hiding
# it strands the user on one page when the sidebar is collapsed.
st.markdown(
    """
    <style>
    #MainMenu, footer,
    [data-testid="stAppDeployButton"],
    [data-testid="stMainMenu"] {display: none;}
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stExpandSidebarButton"] {
        visibility: visible !important;
        display: flex !important;
    }
    .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1150px;}
    h1 {font-weight: 650; letter-spacing: -0.02em;}
    h2, h3 {font-weight: 600;}
    [data-testid="stMetric"] {
        background: rgba(128,128,128,0.07);
        border-radius: 10px;
        padding: 12px 16px;
    }
    [data-testid="stSidebar"] {min-width: 250px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# Categorical chart palette (validated reference set, fixed slot order).
CHART_PALETTE = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948"]

MESSAGE_LABELS = {
    "email_outreach": "Email outreach",
    "email_follow_up": "Email follow-up sequence",
    "linkedin_outreach": "LinkedIn outreach",
    "linkedin_follow_up": "LinkedIn follow-up sequence",
    "instagram_outreach": "Instagram outreach",
    "instagram_follow_up": "Instagram follow-up sequence",
    "facebook_outreach": "Facebook outreach",
    "facebook_follow_up": "Facebook follow-up sequence",
    "loom_script": "Loom script",
}

CHANNEL_TABS = [
    ("Email", "email", ["email_outreach", "email_follow_up"]),
    ("LinkedIn", "linkedin", ["linkedin_outreach", "linkedin_follow_up"]),
    ("Instagram", "instagram", ["instagram_outreach", "instagram_follow_up"]),
    ("Facebook", "facebook", ["facebook_outreach", "facebook_follow_up"]),
    ("Loom", "loom", ["loom_script"]),
]

VARIANT_LABELS = {
    "direct": "Direct",
    "short": "Short",
    "curiosity": "Curiosity",
    "objection_aware": "Objection-aware",
}

SIGNAL_FIELDS = [
    ("Evening or Saturday hours", "evening_or_saturday_hours"),
    ("Single location", "single_location"),
    ("Has chatbot", "has_chatbot"),
    ("Mentions emergency or same-day", "mentions_emergency_or_same_day"),
    ("Has after-hours number", "has_after_hours_number"),
    ("Already has AI receptionist", "already_has_ai_receptionist"),
]


# ---------------------------------------------------------------- Import page

def import_page():
    st.title("Import leads")
    st.caption(
        "Upload any CSV. The app detects what each column means, shows you "
        "the mapping to confirm, then imports. Raw columns are always kept."
    )
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
    if uploaded is None:
        st.info("Upload a CSV to begin. Messy scraped exports are fine.")
        _show_import_history()
        return

    upload_dir = BASE_DIR / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / uploaded.name
    target.write_bytes(uploaded.getvalue())

    headers, proposals = import_leads.detect(target)
    if not headers:
        st.error("That file has no readable header row.")
        return

    st.subheader("Review the column mapping")
    st.caption(
        "Confidence under 0.70 is flagged. Set a column to 'raw only' to keep "
        "it as data without mapping it. Duplicate targets are auto-resolved."
    )
    field_options = ["(raw only)"] + list(csv_mapper.CANONICAL_FIELDS)
    chosen = {}
    # Wide exports (Apify has 700+ columns) would drown the review in
    # noise. Show mapped columns for editing; unmapped stay raw.
    show_all = len(proposals) <= 40
    editable = proposals if show_all else [p for p in proposals if p["field"]]
    hidden = [] if show_all else [p for p in proposals if not p["field"]]
    for i, proposal in enumerate(editable):
        col_h, col_map, col_conf = st.columns([3, 3, 4])
        col_h.markdown(f"**{proposal['header']}**")
        default = proposal["field"] or "(raw only)"
        selection = col_map.selectbox(
            "maps to", field_options,
            index=field_options.index(default) if default in field_options else 0,
            key=f"map_{i}", label_visibility="collapsed",
        )
        chosen[proposal["header"]] = None if selection == "(raw only)" else selection
        conf = proposal["confidence"]
        flag = "" if conf >= csv_mapper.LOW_CONFIDENCE or proposal["field"] is None else "  (check this)"
        col_conf.caption(f"auto: {conf:.2f} {proposal['reason']}{flag}")
    if hidden:
        with st.expander(f"{len(hidden)} unmapped columns (kept as raw data on every lead)"):
            names = ", ".join(p["header"] for p in hidden[:120])
            if len(hidden) > 120:
                names += f" ... and {len(hidden) - 120} more"
            st.caption(names)

    mapped_fields = [f for f in chosen.values() if f]
    if "business_name" not in mapped_fields and "contact_name" not in mapped_fields:
        st.warning("No column maps to business_name or contact_name. Map one before importing.")
    if not any(f in mapped_fields for f in ("email", "phone", "website")):
        st.warning("No email, phone, or website mapped. Leads will have no contact method.")

    if st.button("Import with this mapping", type="primary"):
        header_map = {h: f for h, f in chosen.items() if f}
        summary = import_leads.import_with_mapping(target, header_map, uploaded.name)
        st.success(
            f"Imported {summary['imported']}. Disqualified {summary['disqualified']}. "
            f"Duplicates skipped {summary['duplicates']}. Batch #{summary['batch_id']}."
        )
        if summary["errors"]:
            with st.expander(f"Validation notes ({len(summary['errors'])})"):
                for error in summary["errors"]:
                    st.write("- " + error)
    _show_import_history()


def _show_import_history():
    batches = db.get_import_batches()
    if not batches:
        return
    st.subheader("Import history")
    st.dataframe(
        [{
            "Batch": b["id"], "File": b["source_file"],
            "Imported": b["rows_imported"], "Disqualified": b["rows_disqualified"],
            "Duplicates": b["rows_duplicate"], "When": b["created_at"],
        } for b in batches],
        hide_index=True, use_container_width=True,
    )


# ----------------------------------------------------------------- Leads page

def leads_page():
    st.title("Leads")
    all_leads = db.get_leads()
    if not all_leads:
        st.info("No leads yet. Use the Import page to add some.")
        return
    chosen_statuses = st.multiselect(
        "Filter by status", list(db.LEAD_STATUSES), default=list(db.LEAD_STATUSES)
    )
    visible = [l for l in all_leads if l["status"] in chosen_statuses]
    table = [{
        "ID": l["id"], "Score": l["intent_score"], "Business": l["clinic_name"],
        "Status": l["status"], "Outcome": l.get("outcome") or "",
        "Location": l["location"], "Niche": l.get("niche") or "",
        "Enriched": "yes" if (l["enrichment_angle"] or "").strip() else "",
        "Website": l["website"],
    } for l in visible]
    st.caption(
        f"{len(visible)} lead(s), sorted by score. Click rows to select, "
        "then delete one or many below."
    )
    event = st.dataframe(
        table, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="multi-row", key="leads_table",
    )
    selected_rows = list(event.selection.rows) if event is not None else []
    if selected_rows:
        selected_ids = [visible[i]["id"] for i in selected_rows if i < len(visible)]
        preview = ", ".join(visible[i]["clinic_name"] for i in selected_rows[:5] if i < len(visible))
        if len(selected_ids) > 5:
            preview += f" and {len(selected_ids) - 5} more"
        st.warning(f"Selected: {preview}")
        sure = st.checkbox(
            f"Yes, permanently delete {len(selected_ids)} lead(s) "
            "with their drafts and logged results"
        )
        if st.button("Delete selected", type="primary", disabled=not sure):
            deleted = db.delete_leads(selected_ids)
            st.success(f"Deleted {deleted} lead(s).")
            st.rerun()

    with st.expander("Auto-clean: delete leads by rule"):
        st.caption(
            "Leads matching ALL chosen conditions are deleted. "
            "You see the matches before anything happens."
        )
        c1, c2, c3 = st.columns(3)
        rule_statuses = c1.multiselect("Status is", list(db.LEAD_STATUSES), key="ac_status")
        rule_outcomes = c2.multiselect(
            "Outcome is", ["not set"] + list(db.LEAD_OUTCOMES), key="ac_outcome"
        )
        batches = db.get_import_batches()
        batch_labels = {f"#{b['id']} {b['source_file']}": b["id"] for b in batches}
        rule_batches = c3.multiselect("From import batch", list(batch_labels), key="ac_batch")
        use_score = st.checkbox("Also require score at or below a cap", key="ac_use_score")
        score_cap = None
        if use_score:
            score_cap = st.number_input("Score cap", value=0, key="ac_score")

        any_rule = bool(rule_statuses or rule_outcomes or rule_batches or use_score)
        if not any_rule:
            st.caption("Pick at least one condition to build the rule.")
            return
        matched = []
        wanted_batches = [batch_labels[b] for b in rule_batches]
        for l in all_leads:
            if rule_statuses and l["status"] not in rule_statuses:
                continue
            if rule_outcomes:
                value = (l.get("outcome") or "").strip() or "not set"
                if value not in rule_outcomes:
                    continue
            if wanted_batches and l.get("import_batch_id") not in wanted_batches:
                continue
            if use_score and l["intent_score"] > score_cap:
                continue
            matched.append(l)
        st.write(f"Rule matches {len(matched)} lead(s).")
        for l in matched[:10]:
            st.caption(f"- {l['clinic_name']} (score {l['intent_score']}, {l['status']})")
        if len(matched) > 10:
            st.caption(f"...and {len(matched) - 10} more")
        if matched:
            confirm = st.checkbox(
                f"Yes, permanently delete these {len(matched)} lead(s)", key="ac_confirm"
            )
            if st.button("Delete matched leads", disabled=not confirm, key="ac_delete"):
                deleted = db.delete_leads([l["id"] for l in matched])
                st.success(f"Deleted {deleted} lead(s).")
                st.rerun()


# ------------------------------------------------------------- Lead workspace

def lead_edit_form(lead):
    with st.expander("Edit lead details and signals (score recomputes on save)"):
        with st.form(f"edit_lead_{lead['id']}"):
            col_a, col_b = st.columns(2)
            with col_a:
                owner = st.text_input("Owner / first name", value=lead.get("owner_first_name") or "")
                email = st.text_input("Email", value=lead["email"] or "")
                phone = st.text_input("Phone", value=lead["phone"] or "")
                website = st.text_input("Website", value=lead["website"] or "")
                niche = st.text_input("Niche / specialty", value=lead.get("niche") or "")
                notes = st.text_area("Notes", value=lead["notes"] or "", height=80)
            with col_b:
                flag_options = ["", "Y", "N"]
                flags = {}
                for label, field in SIGNAL_FIELDS:
                    current = lead[field] or ""
                    flags[field] = st.selectbox(
                        label, flag_options,
                        index=flag_options.index(current) if current in flag_options else 0,
                    )
                reviews = st.number_input("Review count", min_value=0, value=int(lead["review_count"] or 0))
            if st.form_submit_button("Save lead"):
                updated = {
                    "owner_first_name": owner.strip(), "email": email.strip(),
                    "phone": phone.strip(), "website": website.strip(),
                    "niche": niche.strip(), "notes": notes.strip(),
                    "review_count": int(reviews),
                }
                updated.update(flags)
                merged = dict(lead)
                merged.update(updated)
                score, disqualified = import_leads.compute_score(merged)
                updated["intent_score"] = score
                if disqualified and lead["status"] != "skipped":
                    updated["status"] = "skipped"
                elif not disqualified and lead["status"] == "skipped":
                    updated["status"] = "imported"
                db.update_lead_fields(lead["id"], updated)
                st.rerun()
        st.divider()
        sure = st.checkbox(
            "Yes, permanently delete this lead with its drafts and logged results",
            key=f"delok_{lead['id']}",
        )
        if st.button("Delete this lead", key=f"dellead_{lead['id']}", disabled=not sure):
            db.delete_leads([lead["id"]])
            st.rerun()


def render_message(message, lead):
    label = MESSAGE_LABELS.get(message["message_type"], message["message_type"])
    variant = message.get("variant") or "direct"
    suffix = f" - {VARIANT_LABELS.get(variant, variant)}" if message["message_type"] in db.OUTREACH_TYPES else ""
    st.markdown(f"**{label}{suffix}** ({message['status']})")
    content = message["content_edited"] or message["content_generated"]
    key = f"msg_{message['id']}"
    st.text_area("Message text", value=content, height=260, key=key, label_visibility="collapsed")
    current = st.session_state.get(key, content)
    st.caption("Quick copy: use the button in the top-right of the grey box.")
    st.code(current, language=None)
    hits = company.check_prohibited(current)
    if hits:
        st.warning("Brand check flagged: " + ", ".join(hits))
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Save edit", key=f"save_{message['id']}"):
        db.update_message_content(message["id"], st.session_state[key])
        st.rerun()
    if message["status"] == "draft":
        if c2.button("Approve", key=f"appr_{message['id']}"):
            db.update_message_content(message["id"], st.session_state[key])
            db.set_message_status(message["id"], "approved")
            if db.count_approved_messages(lead["id"]) >= 1:
                db.set_lead_status(lead["id"], "reviewed")
            st.rerun()
    elif message["status"] == "approved":
        if c2.button("Back to draft", key=f"un_{message['id']}"):
            db.set_message_status(message["id"], "draft")
            st.rerun()
    else:
        c2.caption("Exported")


def workspace_page():
    st.title("Lead workspace")
    leads = db.get_leads()
    if not leads:
        st.info("No leads yet. Import a CSV first.")
        return
    labels = {
        f"#{l['id']}  score {l['intent_score']}  {l['clinic_name']}  ({l['status']})": l["id"]
        for l in leads
    }
    choice = st.selectbox("Pick a lead", list(labels))
    lead = db.get_lead(labels[choice])

    if lead["status"] == "skipped":
        st.warning("Disqualified on import: already uses an AI receptionist.")

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Score:** {lead['intent_score']} | **Status:** {lead['status']}")
        st.markdown(f"**Website:** {lead['website'] or 'none'}")
        st.markdown(f"**Location:** {lead['location'] or 'unknown'} | **Niche:** {lead.get('niche') or 'unknown'}")
        st.markdown(f"**Phone:** {lead['phone'] or 'none'} | **Email:** {lead['email'] or 'none'}")
        try:
            socials = json.loads(lead.get("social_links") or "{}")
        except json.JSONDecodeError:
            socials = {}
        if socials:
            st.markdown("**Social:** " + ", ".join(f"{k}: {v}" for k, v in socials.items()))
        if lead["notes"]:
            st.markdown(f"**Notes:** {lead['notes']}")
    with right:
        for label, field in SIGNAL_FIELDS:
            st.markdown(f"**{label}:** {lead[field] or 'unknown'}")
        st.markdown(f"**Review count:** {lead['review_count']}")

    lead_edit_form(lead)

    if (lead["enrichment_summary"] or "").strip() or (lead["enrichment_angle"] or "").strip():
        st.info(
            f"**Enrichment summary:** {lead['enrichment_summary'] or 'none'}\n\n"
            f"**Enrichment angle:** {lead['enrichment_angle'] or 'none'}"
        )

    if st.button("Generate drafts for every channel", type="primary"):
        generate_drafts.generate_for_lead(lead["id"])
        st.rerun()
    st.caption("Instant. Plain templates, no model call, no network.")

    messages = db.get_messages_for_lead(lead["id"])
    if not messages:
        st.info("No drafts yet. Click the generate button above.")
        return
    by_type = {}
    for m in messages:
        by_type.setdefault(m["message_type"], []).append(m)

    tabs = st.tabs([name for name, _, _ in CHANNEL_TABS])
    for tab, (name, channel, types) in zip(tabs, CHANNEL_TABS):
        with tab:
            outreach_type = next((t for t in types if t in db.OUTREACH_TYPES), None)
            if outreach_type:
                col_v, col_b = st.columns([2, 1])
                variant = col_v.selectbox(
                    "Copy angle", list(db.VARIANTS),
                    format_func=lambda v: VARIANT_LABELS.get(v, v),
                    key=f"variant_{lead['id']}_{channel}",
                )
                rec, reason = generate_drafts.best_variant(outreach_type)
                col_v.caption(f"Recommended: {VARIANT_LABELS.get(rec, rec)}. Why: {reason}")
                if col_b.button(f"Regenerate {name}", key=f"regen_{channel}"):
                    for t in types:
                        generate_drafts.generate_for_lead(lead["id"], only_type=t, variant=variant)
                    st.rerun()
            found = False
            for t in types:
                for m in by_type.get(t, []):
                    render_message(m, lead)
                    found = True
            if not found:
                st.caption("No drafts for this channel yet.")


# -------------------------------------------------------------- Feedback page

def feedback_page():
    st.title("Log outreach outcome")
    st.caption(
        "Record what happened after you sent. This is the whole learning loop. "
        "The copy engine ranks angles by the outcomes you log here."
    )
    leads = db.get_leads()
    if not leads:
        st.info("No leads yet.")
        return
    labels = {f"#{l['id']}  {l['clinic_name']}": l["id"] for l in leads}
    choice = st.selectbox("Lead", list(labels))
    lead_id = labels[choice]

    with st.form("log_outcome"):
        c1, c2 = st.columns(2)
        with c1:
            channel = st.selectbox("Channel used", list(db.OUTREACH_CHANNELS))
            message_type = st.selectbox("Message type", list(db.OUTREACH_TYPES))
            variant = st.selectbox("Copy angle used", list(db.VARIANTS),
                                   format_func=lambda v: VARIANT_LABELS.get(v, v))
            outcome = st.selectbox("Outcome", list(db.OUTCOME_OPTIONS))
            reply_quality = st.selectbox("Reply quality", list(db.REPLY_QUALITIES))
        with c2:
            meeting = st.checkbox("Meeting booked")
            objection = st.selectbox("Objection type", list(db.OBJECTION_TYPES))
            stage = st.selectbox("Conversion stage reached", list(db.CONVERSION_STAGES))
            rating = st.slider("Your rating of the copy (optional)", 0, 5, 0)
            notes = st.text_area("Notes", height=80)
        if st.form_submit_button("Save outcome", type="primary"):
            db.log_outreach({
                "lead_id": lead_id, "channel": channel, "message_type": message_type,
                "variant": variant, "outcome": outcome, "reply_quality": reply_quality,
                "meeting_booked": meeting, "objection_type": objection,
                "conversion_stage": stage, "rating": rating, "notes": notes,
            })
            st.success("Logged. Future drafts will weigh this in.")

    logs = db.get_outreach_logs()
    if logs:
        st.subheader("Recent outcomes")
        st.dataframe([{
            "When": l["created_at"], "Lead": l["lead_id"], "Channel": l["channel"],
            "Type": l["message_type"], "Angle": l["variant"], "Outcome": l["outcome"],
            "Booked": "yes" if l["meeting_booked"] else "", "Synced": "yes" if l["synced"] else "no",
        } for l in logs[:30]], hide_index=True, use_container_width=True)


# --------------------------------------------------------------- Results page

def donut_chart(title, pairs):
    """Donut with fixed slot colors, max 5 slices plus Other, spacer gaps.

    The exact numbers always appear in the tables on this page, which
    covers readers who cannot rely on the colors alone.
    """
    pairs = [(label, count) for label, count in pairs if count > 0]
    if not pairs:
        st.caption(f"{title}: no data yet.")
        return
    pairs.sort(key=lambda p: -p[1])
    if len(pairs) > 5:
        head, tail = pairs[:5], pairs[5:]
        head.append(("other", sum(c for _, c in tail)))
        pairs = head
    labels = [p[0] for p in pairs]
    spec = {
        "data": {"values": [{"label": l, "value": c} for l, c in pairs]},
        "mark": {"type": "arc", "innerRadius": 55, "padAngle": 0.02},
        "encoding": {
            "theta": {"field": "value", "type": "quantitative"},
            "color": {
                "field": "label", "type": "nominal",
                "scale": {"domain": labels, "range": CHART_PALETTE[:len(labels)]},
                "legend": {"title": None, "orient": "right"},
            },
            "tooltip": [
                {"field": "label", "title": "Group"},
                {"field": "value", "title": "Count"},
            ],
        },
        "view": {"stroke": None},
    }
    st.markdown(f"**{title}**")
    st.vega_lite_chart(spec, use_container_width=True)


PIPELINE_STAGES = [
    ("Imported", "imported"),
    ("Drafts ready", "drafts_generated"),
    ("Reviewed", "reviewed"),
    ("Sent", "exported"),
    ("Disqualified", "skipped"),
]


def pipeline_kanban(leads):
    """Read-only kanban of the pipeline. Status moves happen in the workflow."""
    st.subheader("Pipeline")
    columns = st.columns(len(PIPELINE_STAGES))
    for column, (label, status_key) in zip(columns, PIPELINE_STAGES):
        group = [l for l in leads if l["status"] == status_key]
        column.markdown(f"**{label}**")
        column.caption(f"{len(group)} lead(s)")
        for l in group[:8]:
            with column.container(border=True):
                st.markdown(f"**{l['clinic_name'][:30]}**")
                meta = f"score {l['intent_score']}"
                if (l.get("outcome") or "").strip():
                    meta += f" · {l['outcome']}"
                st.caption(meta)
        if len(group) > 8:
            column.caption(f"+{len(group) - 8} more")


def results_page():
    st.title("Results")
    logs = db.get_outreach_logs()
    leads = db.get_leads()

    pipeline_kanban(leads)
    st.divider()

    if not logs:
        st.info("No outcomes logged yet. Use the Feedback page after you send.")
        return

    chart_left, chart_right = st.columns(2)
    with chart_left:
        outcome_counts = {}
        for l in logs:
            key = l["outcome"] or "not set"
            outcome_counts[key] = outcome_counts.get(key, 0) + 1
        donut_chart("Outcome mix", list(outcome_counts.items()))
    with chart_right:
        channel_counts = {}
        for l in logs:
            key = l["channel"] or "unknown"
            channel_counts[key] = channel_counts.get(key, 0) + 1
        donut_chart("Outreach volume by channel", list(channel_counts.items()))

    positive = db.POSITIVE_OUTCOMES

    def rate(rows):
        if not rows:
            return "no data"
        hits = sum(1 for r in rows if r["outcome"] in positive)
        return f"{hits}/{len(rows)} ({100 * hits // len(rows)}%)"

    st.subheader("Reply rate by channel")
    any_channel = False
    for channel in db.OUTREACH_CHANNELS:
        rows = [l for l in logs if l["channel"] == channel]
        if rows:
            any_channel = True
            st.markdown(f"**{channel}:** {rate(rows)} positive")
    if not any_channel:
        st.caption("No channel data yet.")

    st.subheader("Best-performing copy angle (by channel and type)")
    stats = db.variant_stats()
    rows = []
    for (mtype, variant), (wins, total) in sorted(stats.items()):
        rows.append({
            "Channel/type": mtype, "Angle": VARIANT_LABELS.get(variant, variant),
            "Sends": total, "Positive": wins,
            "Win rate": f"{100 * wins // total}%" if total else "0%",
        })
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.caption("Log a few outcomes to populate this.")

    st.subheader("Objections heard")
    obj = {}
    for l in logs:
        if l["objection_type"]:
            obj[l["objection_type"]] = obj.get(l["objection_type"], 0) + 1
    if obj:
        st.dataframe([{"Objection": k, "Count": v} for k, v in sorted(obj.items(), key=lambda x: -x[1])],
                     hide_index=True)
    else:
        st.caption("No objections logged yet.")

    st.subheader("Volume and conversion")
    booked = sum(1 for l in logs if l["meeting_booked"] or l["outcome"] == "booked_call")
    won = sum(1 for l in logs if l["outcome"] == "closed_won")
    c1, c2, c3 = st.columns(3)
    c1.metric("Outreach logged", len(logs))
    c2.metric("Calls booked", booked)
    c3.metric("Closed won", won)

    st.subheader("Conversion per import batch")
    batch_rows = []
    for b in db.get_import_batches():
        b_leads = [l for l in leads if l.get("import_batch_id") == b["id"]]
        contacted = [l for l in b_leads if l["status"] == "exported"]
        batch_rows.append({
            "Batch": b["id"], "File": b["source_file"],
            "Leads": len(b_leads), "Contacted": len(contacted),
        })
    if batch_rows:
        st.dataframe(batch_rows, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- Export page

def export_page():
    st.title("Export")
    tab_send, tab_data = st.tabs(["Approved copy (for sending)", "Data exports"])

    with tab_send:
        ready = db.get_export_ready_leads()
        if not ready:
            st.info("No leads ready. Approve at least one message for a lead.")
        else:
            st.write(f"{len(ready)} lead(s) ready:")
            for l in ready:
                st.write(f"- score {l['intent_score']}: {l['clinic_name']} "
                         f"({db.count_approved_messages(l['id'])} approved)")
            if st.button("Export approved copy to files"):
                result = export_script.export_all()
                st.success(f"Exported {len(result['folders'])} lead(s).")
                if result["csv_path"]:
                    st.write(f"Combined CSV: {result['csv_path']}")
        st.caption(f"Files land in {export_script.EXPORTS_DIR}")

    with tab_data:
        st.caption("Filtered CSV downloads. Nothing leaves the laptop unless you share the file.")
        kind = st.selectbox("What to export", ["Leads", "Outreach outcomes"])
        if kind == "Leads":
            status_filter = st.multiselect("Status", list(db.LEAD_STATUSES), default=list(db.LEAD_STATUSES))
            rows = [l for l in db.get_leads() if l["status"] in status_filter]
            st.download_button("Download leads CSV", export_script.leads_to_csv(rows),
                               file_name=f"leads_{date.today().isoformat()}.csv", mime="text/csv")
            st.write(f"{len(rows)} row(s).")
        else:
            channel_filter = st.multiselect("Channel", list(db.OUTREACH_CHANNELS), default=list(db.OUTREACH_CHANNELS))
            rows = [l for l in db.get_outreach_logs() if (l["channel"] in channel_filter or not l["channel"])]
            st.download_button("Download outcomes CSV", export_script.logs_to_csv(rows),
                               file_name=f"outcomes_{date.today().isoformat()}.csv", mime="text/csv")
            st.write(f"{len(rows)} row(s).")


# ------------------------------------------------------------- Reference page

def reference_page():
    st.title("Reference: sales line library")
    st.caption("Approved lines by category. Mark preferred or retired. Add new lines here, no code needed.")
    lines = company.load_sales_lines()
    changed = False
    for category in company.SALES_CATEGORIES:
        st.subheader(category.replace("_", " ").title())
        items = lines.get(category, [])
        for i, item in enumerate(items):
            c1, c2, c3 = st.columns([6, 2, 1])
            prefix = "* " if item.get("status") == "preferred" else ""
            prefix += "(retired) " if item.get("status") == "retired" else ""
            c1.write(prefix + item["text"])
            new_status = c2.selectbox(
                "status", list(company.LINE_STATUSES),
                index=list(company.LINE_STATUSES).index(item.get("status", "active"))
                if item.get("status", "active") in company.LINE_STATUSES else 0,
                key=f"ls_{category}_{i}", label_visibility="collapsed")
            if new_status != item.get("status"):
                item["status"] = new_status
                changed = True
            if c3.button("Delete", key=f"del_{category}_{i}"):
                items.pop(i)
                company.save_sales_lines(lines)
                st.rerun()
        new_line = st.text_input(f"Add a {category} line", key=f"add_{category}")
        if st.button(f"Add to {category}", key=f"addbtn_{category}") and new_line.strip():
            items.append({"text": new_line.strip(), "status": "active"})
            lines[category] = items
            company.save_sales_lines(lines)
            st.rerun()
        st.divider()
    if changed:
        company.save_sales_lines(lines)

    for name in ("objections_playbook.md", "cta_lines.md", "template_suggestions.md"):
        path = BASE_DIR / "reference" / name
        if path.exists():
            with st.expander(name):
                st.markdown(path.read_text(encoding="utf-8"))


# ----------------------------------------------------------------- Admin page

def _admin_pin():
    try:
        import yaml
        return str((yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8")) or {}).get("admin_pin", ""))
    except Exception:
        return ""


def admin_gate():
    """Light PIN gate. Set admin_pin in config.yaml to enable it."""
    pin = _admin_pin()
    if not pin:
        return True
    if st.session_state.get("admin_ok"):
        return True
    entered = st.text_input("Admin PIN", type="password")
    if st.button("Unlock") and entered == pin:
        st.session_state["admin_ok"] = True
        st.rerun()
    if entered and entered != pin:
        st.error("Wrong PIN.")
    return False


def _parse_pairs(text):
    """Parse `key: value` lines. A bare URL gets its platform inferred,
    so pasting a link alone does the right thing."""
    pairs = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith(("http://", "https://", "www.")):
            platform = next(
                (name for name in ("facebook", "instagram", "linkedin", "tiktok", "whatsapp")
                 if name in lowered),
                "website",
            )
            pairs[platform] = line
        elif ":" in line:
            k, v = line.split(":", 1)
            if k.strip():
                pairs[k.strip()] = v.strip()
    return pairs


def admin_page():
    st.title("Admin: company profile")
    if not admin_gate():
        st.caption("Set admin_pin in config.yaml to protect this page. Empty means open access.")
        return
    st.caption(
        f"Active tenant: {db.active_tenant()}. Edit here instead of changing code. "
        "Every save keeps a restorable version."
    )
    profile = company.load_profile()

    def list_field(label, key, help_text=""):
        text = st.text_area(label, value="\n".join(profile.get(key, [])), help=help_text, height=100)
        return [line.strip() for line in text.splitlines() if line.strip()]

    with st.form("company_form"):
        c1, c2 = st.columns(2)
        with c1:
            profile["company_name"] = st.text_input("Company name", value=profile.get("company_name", ""))
            profile["founder_name"] = st.text_input("Founder name (signs copy)", value=profile.get("founder_name", ""))
            profile["product_name"] = st.text_input("Product name", value=profile.get("product_name", ""))
            profile["calendar_name"] = st.text_input("Calendar name (Loom)", value=profile.get("calendar_name", ""))
            profile["contact_email"] = st.text_input("Contact email", value=profile.get("contact_email", ""))
            profile["website"] = st.text_input("Website", value=profile.get("website", ""))
            profile["demo_url"] = st.text_input("Demo URL", value=profile.get("demo_url", ""))
        with c2:
            profile["offer_summary"] = st.text_area("Offer summary", value=profile.get("offer_summary", ""), height=80)
            profile["pricing_summary"] = st.text_area("Pricing summary", value=profile.get("pricing_summary", ""), height=80)
            profile["target_customer"] = st.text_area("Target customer", value=profile.get("target_customer", ""), height=80)
            profile["fallback_rules"] = st.text_area("Fallback copy rules", value=profile.get("fallback_rules", ""), height=80)

        profile["brand_voice"] = list_field("Brand voice (one rule per line)", "brand_voice")
        profile["services"] = list_field("Services (one per line)", "services")
        profile["pain_points"] = list_field("Pain points (one per line)", "pain_points")
        profile["proof_points"] = list_field("Proof points (one per line)", "proof_points")
        profile["prohibited_phrases"] = list_field(
            "Prohibited phrases (one per line, blocked in copy)", "prohibited_phrases")

        st.markdown("**Social links** (one per line as `platform: url`)")
        social_text = st.text_area(
            "social", value="\n".join(f"{k}: {v}" for k, v in profile.get("social_links", {}).items()),
            label_visibility="collapsed", height=80)
        st.markdown("**Channel rules** (one per line as `channel: rule`)")
        channel_text = st.text_area(
            "channels", value="\n".join(f"{k}: {v}" for k, v in profile.get("channel_rules", {}).items()),
            label_visibility="collapsed", height=120)

        if st.form_submit_button("Save company profile", type="primary"):
            profile["social_links"] = _parse_pairs(social_text)
            profile["channel_rules"] = _parse_pairs(channel_text)
            company.save_profile(profile)
            st.success("Saved. A restorable version was kept.")

    st.subheader("Version history")
    versions = company.list_profile_versions()
    if versions:
        pick = st.selectbox("Saved versions", versions)
        if st.button("Restore this version"):
            company.restore_profile_version(pick)
            st.success("Restored. Reload to see it.")
    else:
        st.caption("No prior versions yet. They appear here after your first save.")


# --------------------------------------------------------------------- Router

_profile = company.load_profile()
_logo = BASE_DIR / "assets" / "logo_transparent.png"
if _logo.exists():
    # Plain HTML img, not st.image: no fullscreen button, not clickable.
    import base64
    _logo_b64 = base64.b64encode(_logo.read_bytes()).decode()
    st.sidebar.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">'
        f'<img src="data:image/png;base64,{_logo_b64}" width="40" height="40" '
        'style="pointer-events:none;user-select:none;" alt="">'
        '<span style="font-size:1.3rem;font-weight:650;">Outreach Studio</span>'
        "</div>",
        unsafe_allow_html=True,
    )
else:
    st.sidebar.title("Outreach Studio")
_tenant_name = _profile.get("company_name") or db.active_tenant()
st.sidebar.caption(f"Active workspace: {_tenant_name}")

_unsynced = db.count_unsynced_logs()
if _unsynced:
    st.sidebar.warning(f"{_unsynced} outcome(s) not yet synced")
    if st.sidebar.button("Mark as synced"):
        db.mark_logs_synced()
        st.rerun()
else:
    st.sidebar.success("All outcomes synced")
st.sidebar.caption(
    "Offline-safe: everything here works with no internet. Enrichment, the "
    "learning batch, and the planner sync run from a terminal on purpose."
)

PAGES = {
    "Import": import_page,
    "Leads": leads_page,
    "Lead workspace": workspace_page,
    "Feedback": feedback_page,
    "Results": results_page,
    "Export": export_page,
    "Reference": reference_page,
    "Admin": admin_page,
}
_page = st.sidebar.radio("View", list(PAGES))
PAGES[_page]()
