"""DigiDental outreach app. Runs locally with Streamlit.

This file never calls Ollama and never makes a network request.
Phase 2 enrichment is a separate command line script: scripts\\enrich_batch.py
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

st.set_page_config(page_title="DigiDental Outreach", layout="wide")

MESSAGE_LABELS = {
    "first_contact": "First contact",
    "follow_up": "Follow up",
    "loom_script": "Loom script",
}

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

    if (lead["enrichment_summary"] or "").strip() or (lead["enrichment_angle"] or "").strip():
        st.info(
            f"**Phase 2 summary:** {lead['enrichment_summary'] or 'none'}\n\n"
            f"**Phase 2 angle:** {lead['enrichment_angle'] or 'none'}\n\n"
            "Drafts use the Phase 2 angle when it exists."
        )

    if st.button("Generate drafts"):
        generate_drafts.generate_for_lead(lead["id"])
        st.rerun()
    st.caption("Instant. Plain templates, no model call, no network.")

    messages = db.get_messages_for_lead(lead["id"])
    if not messages:
        st.info("No drafts yet. Click Generate drafts.")
        return
    for message in messages:
        st.subheader(f"{MESSAGE_LABELS[message['message_type']]} ({message['status']})")
        key = f"msg_{message['id']}"
        current = message["content_edited"] or message["content_generated"]
        st.text_area(
            "Message text", value=current, height=320, key=key,
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
                if db.all_messages_approved(lead["id"]):
                    db.set_lead_status(lead["id"], "reviewed")
                st.rerun()
        elif message["status"] == "approved":
            if col_status.button("Back to draft", key=f"unapprove_{message['id']}"):
                db.set_message_status(message["id"], "draft")
                db.set_lead_status(lead["id"], "drafts_generated")
                st.rerun()
        else:
            col_status.caption("Exported")


def export_page():
    st.title("Export")
    ready = db.get_export_ready_leads()
    if not ready:
        st.info("No leads ready. A lead is ready when all three messages are approved.")
    else:
        st.write(f"{len(ready)} lead(s) ready to export:")
        for lead in ready:
            st.write(f"- score {lead['intent_score']}: {lead['clinic_name']}")
        if st.button("Export approved leads"):
            result = export_script.export_all()
            st.success(f"Exported {len(result['folders'])} lead(s).")
            for folder in result["folders"]:
                st.write(str(folder))
            if result["csv_path"]:
                st.write(f"Combined CSV: {result['csv_path']}")
    st.caption(f"Export folder: {export_script.EXPORTS_DIR}")


def reference_page():
    st.title("Reference")
    st.caption(
        "Read-only. Use these when a reply comes in. "
        "Nothing here is generated per lead or sent automatically."
    )
    for name in ("objections_playbook.md", "cta_lines.md"):
        path = BASE_DIR / "reference" / name
        if path.exists():
            st.markdown(path.read_text(encoding="utf-8"))
            st.divider()


page = st.sidebar.radio("View", ["Leads", "Lead workspace", "Export", "Reference"])
st.sidebar.caption(
    "Phase 2 enrichment never runs from this app. Run it from a terminal "
    "when you choose to: python scripts\\enrich_batch.py"
)

if page == "Leads":
    leads_page()
elif page == "Lead workspace":
    workspace_page()
elif page == "Export":
    export_page()
else:
    reference_page()
