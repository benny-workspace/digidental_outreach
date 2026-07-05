"""DigiDental outreach app. Runs locally with Streamlit.

This file never calls Ollama and never makes a network request.
Phase 2 enrichment and the learning batch are separate command line
scripts: scripts\\enrich_batch.py and scripts\\learn_batch.py
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

import streamlit as st

import db
import export as export_script
import generate_drafts
import import_leads

db.init_db()

st.set_page_config(
    page_title="DigiDental Outreach", layout="wide",
    initial_sidebar_state="expanded",
)

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
    ("Email", ["email_outreach", "email_follow_up"]),
    ("LinkedIn", ["linkedin_outreach", "linkedin_follow_up"]),
    ("Instagram", ["instagram_outreach", "instagram_follow_up"]),
    ("Facebook", ["facebook_outreach", "facebook_follow_up"]),
    ("Loom", ["loom_script"]),
]

SIGNAL_FIELDS = [
    ("Evening or Saturday hours", "evening_or_saturday_hours"),
    ("Single location", "single_location"),
    ("Has chatbot", "has_chatbot"),
    ("Mentions emergency or same-day", "mentions_emergency_or_same_day"),
    ("Has after-hours number", "has_after_hours_number"),
    ("Already has AI receptionist", "already_has_ai_receptionist"),
]


def leads_page():
    st.title("Leads")

    with st.expander("Import leads from CSV"):
        st.caption(
            "Columns: clinic_name, website, location, phone, email, source, notes, "
            "evening_or_saturday_hours, single_location, has_chatbot, "
            "mentions_emergency_or_same_day, review_count, has_after_hours_number, "
            "already_has_ai_receptionist. Optional extra column: owner_first_name."
        )
        uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
        if uploaded is not None and st.button("Import this file"):
            upload_dir = BASE_DIR / "data" / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            target = upload_dir / uploaded.name
            target.write_bytes(uploaded.getvalue())
            summary = import_leads.import_csv(target)
            st.success(
                f"Imported {summary['imported']}. "
                f"Disqualified {summary['disqualified']}. "
                f"Duplicates skipped {summary['duplicates']}."
            )
            for error in summary["errors"]:
                st.warning(error)

    chosen_statuses = st.multiselect(
        "Filter by status", list(db.LEAD_STATUSES), default=list(db.LEAD_STATUSES)
    )
    leads = [l for l in db.get_leads() if l["status"] in chosen_statuses]
    if not leads:
        st.info(
            "No leads yet. Import a CSV above, or run: "
            "python scripts\\import_leads.py sample_data\\sample_leads.csv"
        )
        return
    table = [
        {
            "ID": lead["id"],
            "Score": lead["intent_score"],
            "Clinic": lead["clinic_name"],
            "Status": lead["status"],
            "Outcome": lead.get("outcome") or "",
            "Location": lead["location"],
            "Reviews": lead["review_count"],
            "Evening/Sat": lead["evening_or_saturday_hours"],
            "Enriched": "yes" if (lead["enrichment_angle"] or "").strip() else "",
            "Website": lead["website"],
        }
        for lead in leads
    ]
    st.caption("Sorted by intent score, highest first. Work the top of the list.")
    st.dataframe(table, use_container_width=True, hide_index=True)


def render_message(message, lead):
    st.markdown(
        f"**{MESSAGE_LABELS.get(message['message_type'], message['message_type'])}** "
        f"({message['status']})"
    )
    key = f"msg_{message['id']}"
    current = message["content_edited"] or message["content_generated"]
    st.text_area(
        "Message text", value=current, height=300, key=key,
        label_visibility="collapsed",
    )
    col_save, col_status, _ = st.columns([1, 1, 3])
    if col_save.button("Save edit", key=f"save_{message['id']}"):
        db.update_message_content(message["id"], st.session_state[key])
        st.rerun()
    if message["status"] == "draft":
        if col_status.button("Approve", key=f"approve_{message['id']}"):
            db.update_message_content(message["id"], st.session_state[key])
            db.set_message_status(message["id"], "approved")
            if db.count_approved_messages(lead["id"]) >= 1:
                db.set_lead_status(lead["id"], "reviewed")
            st.rerun()
    elif message["status"] == "approved":
        if col_status.button("Back to draft", key=f"unapprove_{message['id']}"):
            db.set_message_status(message["id"], "draft")
            st.rerun()
    else:
        col_status.caption("Exported")


def workspace_page():
    st.title("Lead workspace")
    leads = db.get_leads()
    if not leads:
        st.info("No leads yet. Import a CSV on the Leads page first.")
        return
    labels = {
        f"#{lead['id']}  score {lead['intent_score']}  {lead['clinic_name']}  ({lead['status']})": lead["id"]
        for lead in leads
    }
    choice = st.selectbox("Pick a lead", list(labels))
    lead = db.get_lead(labels[choice])

    if lead["status"] == "skipped":
        st.warning(
            "Disqualified on import: already uses an AI receptionist. "
            "Generate drafts only if you are sure."
        )

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Score:** {lead['intent_score']} | **Status:** {lead['status']}")
        st.markdown(f"**Website:** {lead['website'] or 'none'}")
        st.markdown(f"**Location:** {lead['location'] or 'unknown'}")
        st.markdown(f"**Phone:** {lead['phone'] or 'none'} | **Email:** {lead['email'] or 'none'}")
        st.markdown(f"**Source:** {lead['source'] or 'unknown'}")
        if lead["notes"]:
            st.markdown(f"**Notes:** {lead['notes']}")
    with right:
        for label, field in SIGNAL_FIELDS:
            st.markdown(f"**{label}:** {lead[field] or 'unknown'}")
        st.markdown(f"**Review count:** {lead['review_count']}")

    st.markdown("**Outcome after sending** (also pick the channel the reply came from)")
    outcome_options = [""] + list(db.LEAD_OUTCOMES)
    channel_options = [""] + list(db.OUTREACH_CHANNELS)
    current_outcome = (lead.get("outcome") or "").strip()
    current_channel = (lead.get("outcome_channel") or "").strip()
    col_pick, col_channel, col_save_outcome, _ = st.columns([2, 2, 1, 1])
    picked = col_pick.selectbox(
        "Outcome", outcome_options,
        index=outcome_options.index(current_outcome) if current_outcome in outcome_options else 0,
        key=f"outcome_{lead['id']}", label_visibility="collapsed",
        format_func=lambda value: value if value else "outcome: not set",
    )
    picked_channel = col_channel.selectbox(
        "Channel", channel_options,
        index=channel_options.index(current_channel) if current_channel in channel_options else 0,
        key=f"channel_{lead['id']}", label_visibility="collapsed",
        format_func=lambda value: value if value else "channel: not set",
    )
    if col_save_outcome.button("Save", key=f"save_outcome_{lead['id']}"):
        db.set_lead_outcome(lead["id"], picked, picked_channel)
        st.rerun()

    if (lead["enrichment_summary"] or "").strip() or (lead["enrichment_angle"] or "").strip():
        st.info(
            f"**Phase 2 summary:** {lead['enrichment_summary'] or 'none'}\n\n"
            f"**Phase 2 angle:** {lead['enrichment_angle'] or 'none'}\n\n"
            "Drafts use the Phase 2 angle when it exists. For deeper personalization, "
            "run the enrichment batch before generating drafts."
        )

    if st.button("Generate drafts for every channel"):
        generate_drafts.generate_for_lead(lead["id"])
        st.rerun()
    st.caption("Instant. Plain templates, no model call, no network.")

    messages = db.get_messages_for_lead(lead["id"])
    if not messages:
        st.info("No drafts yet. Click the generate button.")
        return
    by_type = {}
    for message in messages:
        by_type.setdefault(message["message_type"], []).append(message)
    tabs = st.tabs([name for name, _ in CHANNEL_TABS])
    for tab, (name, types) in zip(tabs, CHANNEL_TABS):
        with tab:
            found = False
            for message_type in types:
                for message in by_type.get(message_type, []):
                    render_message(message, lead)
                    found = True
            if not found:
                st.caption("No drafts for this channel yet. Regenerate to create them.")
    leftovers = [m for m in messages if m["message_type"] not in MESSAGE_LABELS]
    for message in leftovers:
        render_message(message, lead)


def export_page():
    st.title("Export")
    ready = db.get_export_ready_leads()
    if not ready:
        st.info("No leads ready. A lead is ready when at least one message is approved.")
    else:
        st.write(f"{len(ready)} lead(s) ready to export:")
        for lead in ready:
            approved = db.count_approved_messages(lead["id"])
            st.write(f"- score {lead['intent_score']}: {lead['clinic_name']} ({approved} message(s) approved)")
        if st.button("Export approved leads"):
            result = export_script.export_all()
            st.success(f"Exported {len(result['folders'])} lead(s).")
            for folder in result["folders"]:
                st.write(str(folder))
            if result["csv_path"]:
                st.write(f"Combined CSV: {result['csv_path']}")
    st.caption(f"Export folder: {export_script.EXPORTS_DIR}")


def results_page():
    st.title("Results")
    st.caption(
        "Record an outcome and channel on each lead after you send. "
        "This page shows what is working so the templates can be sharpened."
    )
    leads = db.get_leads()
    tracked = [l for l in leads if (l.get("outcome") or "").strip()]
    if not tracked:
        st.info("No outcomes recorded yet. Set one in the Lead workspace after you send.")
        return

    counts = {}
    for lead in tracked:
        counts[lead["outcome"]] = counts.get(lead["outcome"], 0) + 1
    st.dataframe(
        [{"Outcome": outcome, "Leads": count} for outcome, count in sorted(counts.items())],
        hide_index=True,
    )

    positive = {"replied", "call_booked", "closed_won"}

    def reply_rate(group):
        if not group:
            return "no data yet"
        hits = sum(1 for l in group if l["outcome"] in positive)
        return f"{hits} of {len(group)}"

    st.subheader("By channel")
    for channel in db.OUTREACH_CHANNELS:
        group = [l for l in tracked if (l.get("outcome_channel") or "") == channel]
        if group:
            st.markdown(f"**{channel}:** {reply_rate(group)} got a reply or better")

    st.subheader("By lead quality")
    enriched = [l for l in tracked if (l["enrichment_angle"] or "").strip()]
    plain = [l for l in tracked if not (l["enrichment_angle"] or "").strip()]
    high_score = [l for l in tracked if l["intent_score"] >= 5]
    low_score = [l for l in tracked if l["intent_score"] < 5]
    st.markdown(f"**With Phase 2 enrichment:** {reply_rate(enriched)} got a reply or better")
    st.markdown(f"**Without enrichment:** {reply_rate(plain)} got a reply or better")
    st.markdown(f"**Score 5 and up:** {reply_rate(high_score)} got a reply or better")
    st.markdown(f"**Score under 5:** {reply_rate(low_score)} got a reply or better")
    st.caption(
        "A reply or better means replied, call_booked, or closed_won. "
        "To turn this data into better templates, run from a terminal: "
        "python scripts\\learn_batch.py "
        "It writes suggestions to reference\\template_suggestions.md for you to review."
    )


def reference_page():
    st.title("Reference")
    st.caption(
        "Read-only. Use these when a reply comes in. "
        "Nothing here is generated per lead or sent automatically."
    )
    for name in ("objections_playbook.md", "cta_lines.md", "template_suggestions.md"):
        path = BASE_DIR / "reference" / name
        if path.exists():
            st.markdown(path.read_text(encoding="utf-8"))
            st.divider()


page = st.sidebar.radio("View", ["Leads", "Lead workspace", "Export", "Results", "Reference"])
st.sidebar.caption(
    "Phase 2 enrichment and the learning batch never run from this app. "
    "Run them from a terminal when you choose to: "
    "python scripts\\enrich_batch.py and python scripts\\learn_batch.py"
)

if page == "Leads":
    leads_page()
elif page == "Lead workspace":
    workspace_page()
elif page == "Export":
    export_page()
elif page == "Results":
    results_page()
else:
    reference_page()
