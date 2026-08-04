"""Rebuild the outreach-studio-copywriter skill from the current repo content.

The .skill file is a zip archive. This script composes it from:
    skill\\SKILL.md                     (master instructions, hand-edited)
    skill\\references\\objections.md     (objection scripts, hand-edited)
    skill\\references\\existing-copy.md  (copy library, hand-edited)
plus an auto-synced section appended to existing-copy.md containing the
live outreach templates from prompts\\ and the CTA lines.

Run it after any template change so the skill and the app never drift:
    python scripts\\build_skill.py

Outputs:
    Documents\SKILLS\outreach-studio-copywriter.skill   (the portable skill file)
    .claude\skills\outreach-studio-copywriter\          (installed for Claude Code)
"""

import sys
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SKILL_DIR = BASE_DIR / "skill"
PROMPTS_DIR = BASE_DIR / "prompts"
REFERENCE_DIR = BASE_DIR / "reference"

SKILL_NAME = "outreach-studio-copywriter"
SKILL_FILE = Path.home() / "Documents" / "SKILLS" / f"{SKILL_NAME}.skill"
CLAUDE_SKILL_DIR = Path.home() / ".claude" / "skills" / SKILL_NAME

TEMPLATE_FILES = [
    ("email_outreach.txt", "Email outreach (pricing-free, current default)"),
    ("email_follow_up.txt", "Email follow-up sequence"),
    ("linkedin_outreach.txt", "LinkedIn outreach"),
    ("linkedin_follow_up.txt", "LinkedIn follow-up sequence"),
    ("instagram_outreach.txt", "Instagram outreach"),
    ("instagram_follow_up.txt", "Instagram follow-up sequence"),
    ("facebook_outreach.txt", "Facebook outreach"),
    ("facebook_follow_up.txt", "Facebook follow-up sequence"),
    ("loom_script.txt", "Loom script"),
    ("email_outreach_with_pricing.txt", "Email outreach with pricing (kept as a variant)"),
]


def read(path):
    return path.read_text(encoding="utf-8")


def build_existing_copy():
    """Static copy library plus the live templates, pulled in fresh each build."""
    parts = [read(SKILL_DIR / "references" / "existing-copy.md")]
    parts.append("\n---\n\n## OUTREACH SYSTEM TEMPLATES (auto-synced from the repo)\n\n")
    parts.append(
        "These are the live templates the outreach app fills per lead. "
        "Placeholders use {single_brace} names. To change them, edit the file "
        "in prompts\\ and rerun: python scripts\\build_skill.py\n"
    )
    for filename, label in TEMPLATE_FILES:
        path = PROMPTS_DIR / filename
        if not path.exists():
            continue
        parts.append(f"\n### {label} (prompts\\{filename})\n\n")
        parts.append("```\n" + read(path).strip() + "\n```\n")
    cta_path = REFERENCE_DIR / "cta_lines.md"
    if cta_path.exists():
        parts.append("\n### CTA lines (reference\\cta_lines.md)\n\n")
        parts.append(read(cta_path).strip() + "\n")
    return "".join(parts)


def main():
    missing = [p for p in (SKILL_DIR / "SKILL.md",
                           SKILL_DIR / "references" / "objections.md",
                           SKILL_DIR / "references" / "existing-copy.md") if not p.exists()]
    if missing:
        for path in missing:
            print(f"Missing skill source file: {path}")
        sys.exit(1)

    files = {
        f"{SKILL_NAME}/SKILL.md": read(SKILL_DIR / "SKILL.md"),
        f"{SKILL_NAME}/references/objections.md": read(SKILL_DIR / "references" / "objections.md"),
        f"{SKILL_NAME}/references/existing-copy.md": build_existing_copy(),
    }

    SKILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SKILL_FILE, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    print(f"Wrote {SKILL_FILE}")

    for name, content in files.items():
        target = CLAUDE_SKILL_DIR / Path(name).relative_to(SKILL_NAME)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(f"Installed for Claude Code at {CLAUDE_SKILL_DIR}")


if __name__ == "__main__":
    main()
