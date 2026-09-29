"""
Write path: a bug gets resolved -> extract the causal story -> retain it.

    bug resolved -> extract (root_cause, fix_type, mechanism) -> retain

Uses the SAME prose format as scripts/step2_seed.py's ticket_to_prose, so a
ticket retained live during the demo looks identical, to Hindsight, to a
ticket from the original seed set. Keep these in sync if you change one.
"""

from typing import Literal

from pydantic import BaseModel, Field

from hindsight_client import Hindsight

from .llm import chat_json


class ResolutionMemory(BaseModel):
    root_cause: str
    fix_applied: str
    fix_type: Literal["real_fix", "workaround", "unknown"]
    fix_type_reason: str
    mechanism_tags: list[str] = Field(default_factory=list)
    lesson: str | None = None


RESOLVE_SYSTEM = """You are a senior engineer writing a post-mortem entry for a team's institutional memory. Given the original bug report and resolution notes, produce a structured memory record.

Definitions:
- root_cause: the underlying MECHANISM that produced the failure, not a restatement of the symptom.
- fix_type = "real_fix" ONLY if the change removes the root cause.
- fix_type = "workaround" if it suppresses or hides the symptom while the root cause remains (examples: raising a timeout, adding retries, scheduled restarts, shortening a cache TTL, hardcoding an offset, a guard covering only one code path).
- fix_type = "unknown" if the notes don't say enough to tell. Do not guess.
- mechanism_tags: 1-4 short lowercase tags naming the mechanism (e.g. "race-condition", "stale-cache", "timezone-naive", "resource-leak").

Return ONLY a JSON object with exactly these keys, no markdown fences, no commentary:
{"root_cause": string, "fix_applied": string, "fix_type": "real_fix"|"workaround"|"unknown", "fix_type_reason": string, "mechanism_tags": [string], "lesson": string|null}"""


def extract_resolution(bug_report: str, resolution_notes: str) -> ResolutionMemory:
    user = f'BUG REPORT:\n"""\n{bug_report}\n"""\n\nRESOLUTION NOTES:\n"""\n{resolution_notes}\n"""'
    return chat_json(RESOLVE_SYSTEM, user, ResolutionMemory)


def resolution_to_prose(ticket_id: str, component: str, symptom_class: str,
                         bug_report: str, mem: ResolutionMemory) -> str:
    """Same shape/tone as Step 2's ticket_to_prose, so this ticket reads like
    the rest of history rather than standing out as a different format."""
    lines = [
        f"Bug {ticket_id} in {component}.",
        f"Symptom ({symptom_class}): {bug_report}",
        f"Root cause: {mem.root_cause}",
        f"Fix applied: {mem.fix_applied}",
        f"Fix type: {mem.fix_type}. Status: closed.",
    ]
    if mem.lesson:
        lines.append(f"Lesson: {mem.lesson}")
    return "\n".join(lines)


def retain_resolution(client: Hindsight, bank_id: str, ticket_id: str, component: str,
                       symptom_class: str, bug_report: str, resolution_notes: str,
                       date_iso: str) -> ResolutionMemory:
    """Full write-path call: extract + retain in one step. Returns the memory
    that was written, so the caller (e.g. the UI) can display what was learned."""
    mem = extract_resolution(bug_report, resolution_notes)
    prose = resolution_to_prose(ticket_id, component, symptom_class, bug_report, mem)
    client.retain(
        bank_id=bank_id,
        content=prose,
        context=f"Resolved bug post-mortem for {ticket_id}",
        timestamp=date_iso,
    )
    return mem
