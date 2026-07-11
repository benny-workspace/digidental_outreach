<div align="center">
# Outreach Studio

A local lead outreach system. Everything runs on this laptop. No paid APIs,
no recurring cost. Outreach Studio is the active workspace; the software itself
is business-agnostic (see the tenant section below).

<a href="https://x.com/bennyuncrowned"><img src="https://img.shields.io/badge/Follow-%40bennyuncrowned-000000?style=flat&logo=x&logoColor=white" alt="Follow on X" /></a>
<a href="https://discord.gg/jm5cxrT694"><img src="https://img.shields.io/badge/Join-Discord-5865F2?style=flat&logo=discord&logoColor=white" alt="Join Discord" /></a>
<a href="https://www.linkedin.com/in/ceobenny/"><img src="https://img.shields.io/badge/ceobenny-LinkedIn-blue" /></a>

<p>
  <strong>English</strong> ·
  <a href="docs/readme/README.es.md">Español</a> ·
  <a href="docs/readme/README.zh-CN.md">简体中文</a> ·
  <a href="docs/readme/README.zh-TW.md">繁體中文</a> ·
  <a href="docs/readme/README.ja.md">日本語</a> ·
  <a href="docs/readme/README.ko.md">한국어</a> ·
  <a href="docs/readme/README.vi.md">Tiếng Việt</a> ·
  <a href="docs/readme/README.hi.md">हिन्दी</a> ·
  <a href="docs/readme/README.bn.md">বাংলা</a> ·
  <a href="docs/readme/README.ar.md">العربية</a> ·
  <a href="docs/readme/README.it.md">Italiano</a> ·
  <a href="docs/readme/README.pt-BR.md">Português (Brasil)</a> ·
  <a href="docs/readme/README.fr.md">Français</a> ·
  <a href="docs/readme/README.ru.md">Русский</a> ·
  <a href="docs/readme/README.tr.md">Türkçe</a>
</p>

<img width="1919" height="909" alt="outreach-studio" src="https://github.com/user-attachments/assets/52b60667-2f88-4ada-840e-92b6bb040d9d" />

## Opening the app

Double-click the **Outreach Studio** icon on the Desktop or Start Menu, or
`Start Outreach.bat` in this folder. The browser opens by itself.
Keep the black window open while you work. Close it when you are done.

The app runs at http://localhost:8501 on this machine only. That is by
design: your lead data never leaves the laptop.

## Setup on a new machine (one time)

1. Install Python 3.12 or newer from python.org (tick "Add python.exe to PATH").
2. Download this repository (Code -> Download ZIP, or `git clone`) and unzip it.
3. In the folder, open PowerShell and run:

       python -m venv venv
       venv\Scripts\python.exe -m pip install -r requirements.txt

4. Start it: double-click `Start Outreach.bat`.
5. Optional: `powershell -ExecutionPolicy Bypass -File scripts\install_shortcuts.ps1`
   creates the Desktop and Start Menu icons.

The first start creates an empty database. Set up your business on the
Admin page, then import leads.

## Smart import

The Import page reads any CSV: Apify, Apollo, Instantly, or a hand-built
list. Column names are recognized by keyword, so `location_business`,
`business_location`, and `Company City` all land on Location, and the same
logic covers every field. You review the proposed mapping once, adjust
anything, and import. Manual column matching is never required.

## The pages (sidebar, top to bottom)

1. **Import** — upload any CSV. The app reads the headers, guesses what each
   column means with a confidence score, and shows a mapping you can correct
   before importing. Messy scraped files are fine. Every raw column is kept.
2. **Leads** — every lead, sorted by score. Work the top down.
3. **Lead workspace** — pick a lead, edit its details and signals, then
   generate drafts for all channels. Each outreach channel has a copy angle
   selector (direct, short, curiosity, objection-aware) and a Regenerate
   button that only touches that channel. A grey box under each message has a
   one-click copy button. Approve what you will send.
4. **Feedback** — after you send, log the outcome (channel, angle, reply
   quality, objection, meeting booked, rating, notes). This is the learning
   loop. The workspace then recommends the angle with the best win rate, and
   tells you why in plain numbers.
5. **Results** — reply rate by channel, best angle by channel, objections
   heard, calls booked, conversion per import batch.
6. **Export** — approved copy to text files, or filtered CSV downloads of
   leads and outcomes.
7. **Reference** — your sales line library by category (pain, curiosity,
   objection, proof, CTA, follow-up). Add, mark preferred, or retire lines.
8. **Admin** — edit the company profile: name, voice, offer, pricing, pain
   points, proof, prohibited phrases, channel rules. No code, no Claude. Every
   save keeps a restorable version. Lock it with `admin_pin` in config.yaml.

The database is a single file: `data\outreach.db`. Copy it to back up every
lead, draft, outcome, and import batch.

## Offline-safe

Everything above works with no internet. New feedback is saved locally and
the sidebar shows how many outcomes are unsynced. The three scripts that need
the internet (enrichment, learning batch, planner sync) run from a terminal on
purpose, never from a button.

## Internal Local Personalization for Businesses

The app is tenant-aware. Business specifics live in `tenants/<tenant>/` and
the Admin page, not in code. To run it for a different business: set `tenant`
in config.yaml to a new name, start the app, and fill in the Admin profile.
Its leads, templates, results, and exports stay separate.

## Phase 2: optional enrichment (needs Ollama, run it on purpose)

Never runs from the app. Run it from a terminal, for example before bed.

    python scripts\enrich_batch.py --limit 2   (test first)
    python scripts\enrich_batch.py             (full batch)

Once you have recorded outcomes on at least 5 leads, the learning batch
turns that data into suggested template edits, written to
`reference\template_suggestions.md` for you to review:

    python scripts\learn_batch.py

Close heavy browser sessions before running either batch.

## Planner sync (optional, Lovable + Supabase)

One-way push of daily summary numbers into your Supabase project so the
Lovable life planner can show them. Lead data never leaves this laptop.

One-time setup:

1. In the Supabase dashboard, open the SQL editor and run:

       create table if not exists outreach_daily (
         day date primary key,
         total_leads int,
         drafts_ready int,
         leads_contacted int,
         replies int,
         calls_booked int,
         closed_won int,
         updated_at timestamptz default now()
       );
       alter table outreach_daily enable row level security;
       create policy "planner can read stats" on outreach_daily
         for select using (true);

2. Copy `config.local.example.yaml` to `config.local.yaml` and fill in
   your project URL and service_role key (Project Settings -> API).
3. Run the sync once to test: double-click `Sync Planner.bat`.

Then run the sync whenever you finish an outreach session. Running it
twice a day is fine, it just refreshes today's row.

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
