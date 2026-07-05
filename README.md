# DigiDental Outreach

A local outreach system for Denty. Everything runs on this laptop. No paid APIs, no recurring cost.

## Opening the app

Double-click `Start Outreach.bat`. The browser opens by itself.
Keep the black window open while you work. Close it when you are done.

## Phase 1: the daily workflow (no model, no internet needed)

1. Build a lead CSV by hand from Google Maps, Yelp, or Apollo. Copy the columns
   from `sample_data/sample_leads.csv`. Add `owner_first_name` as an extra
   column when you know it. Leave a signal column blank if you are not sure.
2. Import and score: `python scripts\import_leads.py path\to\leads.csv`
   or upload the CSV inside the app.
3. Open the app: `streamlit run app.py`
4. Work leads from the top score down. Generate drafts, edit, approve.
5. Export: `python scripts\export.py` or the Export view in the app.
   Files land in `exports\`.
6. After you send and hear back, record the outcome on the lead in the
   workspace. The Results page shows reply rates so you can see what works.
   When a wording works, edit the file in `prompts\`. Every future draft
   inherits the change. That is how the system improves over time.

## Phase 2: optional enrichment (needs Ollama, run it on purpose)

Never runs from the app. Run it from a terminal, for example before bed.

    python scripts\enrich_batch.py --limit 2   (test first)
    python scripts\enrich_batch.py             (full batch)

Close heavy browser sessions before running a large batch.

## Files

- `app.py` review UI. Never calls a model or the network.
- `db.py` all database access.
- `config.yaml` your name, calendar wording, Ollama settings. Edit founder_name first.
- `scripts/` import, draft generation, export, and the optional Phase 2 batch.
- `prompts/` message templates. Plain `{single_brace}` placeholders only.
- `reference/` objection playbook and CTA lines. Read them when a reply comes in.
- `exports/` finished, approved messages as text files.
