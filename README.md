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
6. After you send and hear back, record the outcome and the channel on the
   lead in the workspace. The Results page shows reply rates per channel so
   you can see what works. When a wording works, edit the file in `prompts\`.
   Every future draft inherits the change. That is how the system improves.

Each lead gets drafts for every channel: email, LinkedIn, Instagram, and
Facebook, each with an outreach message and a follow-up sequence, plus the
Loom script. Use the channels that fit the clinic. Approve only what you
will actually send. One approved message is enough to export a lead.

The database is a single file: `data\outreach.db`. Copy it to back up
every lead, draft, and outcome.

## Phase 2: optional enrichment (needs Ollama, run it on purpose)

Never runs from the app. Run it from a terminal, for example before bed.

    python scripts\enrich_batch.py --limit 2   (test first)
    python scripts\enrich_batch.py             (full batch)

Once you have recorded outcomes on at least 5 leads, the learning batch
turns that data into suggested template edits, written to
`reference\template_suggestions.md` for you to review:

    python scripts\learn_batch.py

Close heavy browser sessions before running either batch.

## Copywriter skill sync

The digi-dental-copywriter skill (used by Claude for all Digi Dental copy)
is built from this repo so it always matches the live templates. After you
edit anything in `prompts\` or `reference\`, run:

    python scripts\build_skill.py

That rewrites `Documents\SKILLS\digi-dental-copywriter.skill` and the
installed copy Claude Code uses. The skill source lives in `skill\` and is
kept out of git while this repo is public, because it contains sales tactics.

## Files

- `app.py` review UI. Never calls a model or the network.
- `db.py` all database access.
- `config.yaml` your name, calendar wording, Ollama settings. Edit founder_name first.
- `scripts/` import, draft generation, export, and the optional Phase 2 batch.
- `prompts/` message templates. Plain `{single_brace}` placeholders only.
- `reference/` objection playbook and CTA lines. Read them when a reply comes in.
- `exports/` finished, approved messages as text files.
