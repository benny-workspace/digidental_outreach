"""Learning batch. Optional. Command line only, never run from the app.

Reads your recorded outcomes, sends the performance data and the current
templates to the local Ollama model, and writes suggested template edits
to reference\\template_suggestions.md. Nothing is applied automatically.
You read the suggestions, edit the template files you agree with, and
every future draft inherits the change.

Phase 1 never needs this script. If Ollama is not installed, everything
else keeps working.

Usage:
    python scripts\\learn_batch.py

Close heavy browser sessions before running. The model needs the RAM.
"""

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import yaml

import db

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"
SUGGESTIONS_FILE = BASE_DIR / "reference" / "template_suggestions.md"

MIN_TRACKED_LEADS = 5


def load_config():
    with open(BASE_DIR / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def build_system_prompt(config):
    template = (PROMPTS_DIR / "llm_learn_prompt.txt").read_text(encoding="utf-8")
    return template.format_map(
        defaultdict(str, {"founder_name": str(config.get("founder_name", ""))})
    )


def ollama_is_running(config):
    url = config.get("ollama", {}).get("url", "http://localhost:11434/api/generate")
    base = url.split("/api/")[0]
    try:
        requests.get(base, timeout=5)
        return True
    except requests.RequestException:
        return False


def performance_report():
    """Plain-text summary of outcomes, by channel and by message type."""
    leads = db.get_leads()
    tracked = [l for l in leads if (l.get("outcome") or "").strip()]
    lines = [f"Leads with a recorded outcome: {len(tracked)}"]
    positive = {"replied", "call_booked", "closed_won"}
    by_channel = {}
    for lead in tracked:
        channel = (lead.get("outcome_channel") or "unknown").strip() or "unknown"
        wins, total = by_channel.get(channel, (0, 0))
        by_channel[channel] = (wins + (1 if lead["outcome"] in positive else 0), total + 1)
    for channel, (wins, total) in sorted(by_channel.items()):
        lines.append(f"Channel {channel}: {wins} replies or better out of {total} leads")
    for stat in db.get_sent_message_stats():
        lines.append(
            f"Message type {stat['message_type']}: {stat['n']} sent where lead outcome "
            f"was '{stat['outcome'] or 'not recorded'}' via '{stat['outcome_channel'] or 'unknown'}'"
        )
    return "\n".join(lines), len(tracked)


def current_templates():
    parts = []
    for message_type in db.MESSAGE_TYPES:
        path = PROMPTS_DIR / f"{message_type}.txt"
        if path.exists():
            parts.append(f"--- TEMPLATE {message_type} ---\n{path.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts)


def call_ollama(config, system_prompt, user_prompt):
    ollama = config.get("ollama", {})
    payload = {
        "model": ollama.get("model", "llama3.2:1b"),
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
    }
    response = requests.post(
        ollama.get("url", "http://localhost:11434/api/generate"),
        json=payload,
        timeout=ollama.get("timeout_seconds", 300),
    )
    response.raise_for_status()
    return str(response.json().get("response", "")).strip()


def main():
    print("Reminder: close heavy browser sessions before running.")
    config = load_config()
    if not ollama_is_running(config):
        print("Ollama is not reachable at localhost:11434.")
        print("Start Ollama and try again. Phase 1 keeps working without this.")
        sys.exit(1)

    db.init_db()
    report, tracked_count = performance_report()
    if tracked_count < MIN_TRACKED_LEADS:
        print(f"Only {tracked_count} lead(s) have a recorded outcome.")
        print(f"Record at least {MIN_TRACKED_LEADS} before running this, or the")
        print("suggestions would be guesses instead of learnings.")
        return

    print("Asking the local model for template suggestions. This can take a few minutes on CPU...")
    user_prompt = (
        "PERFORMANCE DATA:\n" + report +
        "\n\nCURRENT TEMPLATES:\n" + current_templates()
    )
    try:
        suggestions = call_ollama(config, build_system_prompt(config), user_prompt)
    except Exception as exc:
        print(f"Model call failed: {exc}")
        sys.exit(1)
    if not suggestions:
        print("Model returned nothing. Try again later.")
        sys.exit(1)

    stamp = date.today().isoformat()
    header = (
        f"# Template Suggestions\n\n"
        f"Generated {stamp} by the local model from your recorded outcomes.\n"
        f"Nothing here is applied automatically. If a suggestion is good,\n"
        f"edit the file in prompts\\ yourself, then every future draft inherits it.\n"
        f"Also rerun: python scripts\\build_skill.py to keep the skill in sync.\n\n"
        f"## Performance data used\n\n```\n{report}\n```\n\n## Suggestions\n\n"
    )
    SUGGESTIONS_FILE.write_text(header + suggestions + "\n", encoding="utf-8")
    print(f"Wrote {SUGGESTIONS_FILE}")
    print("Read it in the app under Reference, or open the file directly.")


if __name__ == "__main__":
    main()
