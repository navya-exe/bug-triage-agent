"""
Shared helpers for the Step 2 scripts.

Place at scripts/common.py. (Temporary home: we move this logic into agent/
in Step 3.) Sibling scripts import it with `from common import ...`.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "bug_tickets_dataset.json"
TICKET_ID_RE = re.compile(r"TICKET-\d{4}")


def load_tickets() -> list[dict]:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return data["tickets"]


def closed_tickets(tickets: list[dict]) -> list[dict]:
    return [t for t in tickets if t["status"] == "closed"]


def open_tickets(tickets: list[dict]) -> list[dict]:
    return [t for t in tickets if t["status"] == "open"]


def _blind(text: str | None) -> str | None:
    """Replace explicit references to other tickets so IDs can't link memories."""
    if not text:
        return text
    return TICKET_ID_RE.sub("an earlier ticket", text)


def ticket_to_prose(t: dict, blind: bool = False) -> str:
    """Readable prose for Hindsight to extract facts from.

    blind=False: realistic post-mortem, cross-references and lessons included.
    blind=True : drops lesson_note / reopened_from and removes explicit ticket
                 references, giving a harder and more honest recall test.
                 (Phrases like "same underlying issue as an earlier ticket"
                 can still survive in root_cause text.)
    """
    root_cause = _blind(t["root_cause"]) if blind else t["root_cause"]
    fix_applied = _blind(t["fix_applied"]) if blind else t["fix_applied"]

    lines = [
        f"Bug {t['ticket_id']} in {t['component']}, reported {t['date']} by {t['reporter']}.",
        f"Symptom ({t['symptom_class']}): {t['symptom_text']}",
        f"Conditions: {t['conditions']}.",
        f"Root cause: {root_cause}",
        f"Fix applied: {fix_applied}",
        f"Fix type: {t['fix_type']}. Status: {t['status']}.",
    ]
    if not blind:
        if t.get("reopened_from"):
            lines.append(f"This ticket followed up on or reopened {t['reopened_from']}.")
        if t.get("lesson_note"):
            lines.append(f"Lesson: {t['lesson_note']}")
    return "\n".join(lines)


def raw_query(t: dict, variant: str) -> str:
    """What a human might paste as a new bug report (no lesson_note, no tags)."""
    if variant == "symptom_only":
        return t["symptom_text"]
    return f"{t['component']}: {t['symptom_text']} Conditions: {t['conditions']}"


def family_members(held_out: dict, closed: list[dict]) -> set[str]:
    """Ground truth for SCORING ONLY. family_tag is a dev field, never retained."""
    tag = held_out.get("family_tag")
    if not tag:
        return set()
    return {t["ticket_id"] for t in closed if t.get("family_tag") == tag}
