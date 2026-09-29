"""
LLM #2 - Reason: new bug + recalled candidates -> verdict.

Design notes:
  - Candidates are looked up from the LOCAL dataset by ticket_id (not from
    Hindsight's recalled fact text), because recalled prose can be partial or
    reworded by Hindsight's own extraction. The local record is the ground
    truth for root_cause / fix_type, and it's also what powers the UI's
    side-by-side card in Step 7. Hindsight is still what SELECTED which
    ticket_ids are relevant - this just fetches full detail once you know
    the ID.
  - If recall found nothing mappable, we skip the LLM call entirely and
    return an automatic no_match. This guarantees the no-match path always
    works, even if the model would be tempted to force a connection.
  - lesson_note and family_tag are NEVER shown to this step. lesson_note
    often states the connection in plain English ("same as TICKET-1001"),
    which would let the model quote the answer instead of reasoning to it.
"""

from typing import Literal

from pydantic import BaseModel, Field

from .llm import chat_json
from .recall import RecalledFact


class Verdict(BaseModel):
    verdict: Literal["recurrence", "related_variant", "no_match"]
    confidence: float = Field(ge=0.0, le=1.0)
    matched_ticket_ids: list[str] = Field(default_factory=list)
    mechanism_reasoning: str
    why_symptoms_look_different: str | None = None
    past_fix_assessment: str | None = None
    likely_root_cause: str
    recommended_action: str
    evidence_gaps: list[str] = Field(default_factory=list)


REASON_SYSTEM = """You are a senior engineer triaging a new bug using your team's recorded history. Decide whether the new bug shares a ROOT CAUSE MECHANISM with a past incident.

CRITICAL RULES:
1. Compare mechanisms, not wording. Two bugs can look completely different to a user and share one cause. Two bugs can use similar words and have unrelated causes.
2. 6. Do not treat a broad problem category as a shared mechanism. Similar high-level categories are not enough by themselves. A related-variant verdict is allowed when the same broader failure mechanism is clearly present but the affected resource or subsystem differs, such as a resource leak causing exhaustion of different resources. However, different external dependencies are distinct mechanisms: latency or failure in one third-party service must not be treated as the same mechanism as latency or failure in another third-party service unless the evidence explicitly connects them through the same dependency, integration path, or causal chain.
3. Do not force a match. If no candidate shares the mechanism, return "no_match". Saying no is a correct, valuable answer - do not pick the least-bad candidate just to have something to say.
4. Use ONLY the candidates provided below. Never cite a ticket that is not in the candidate list. Never invent ticket IDs or details not present in the text given to you.
5. If a past fix was a "workaround", the root cause is likely still present. Say so explicitly in past_fix_assessment and factor it into recommended_action.
6. Be honest about uncertainty. List what evidence is missing in evidence_gaps (e.g. "no stack trace provided", "conditions not specified").

Verdict definitions:
- "recurrence": same underlying root cause mechanism, strong evidence.
- "related_variant": likely same mechanism family, but evidence is partial or the connection is a reasonable hypothesis rather than a strong match.
- "no_match": no candidate shares the mechanism.

Return ONLY a JSON object with exactly these keys, no markdown fences, no commentary:
{"verdict": "recurrence"|"related_variant"|"no_match", "confidence": number 0-1, "matched_ticket_ids": [string], "mechanism_reasoning": string, "why_symptoms_look_different": string|null, "past_fix_assessment": string|null, "likely_root_cause": string, "recommended_action": string, "evidence_gaps": [string]}"""


def _candidate_block(ticket: dict) -> str:
    """Structured candidate text. Deliberately excludes lesson_note/family_tag."""
    return (
        f"[{ticket['ticket_id']}] component={ticket['component']}\n"
        f"  symptom ({ticket['symptom_class']}): {ticket['symptom_text']}\n"
        f"  conditions: {ticket['conditions']}\n"
        f"  root_cause: {ticket['root_cause']}\n"
        f"  fix_applied: {ticket['fix_applied']} (fix_type: {ticket['fix_type']})"
    )


def _automatic_no_match(reason: str) -> Verdict:
    return Verdict(
        verdict="no_match",
        confidence=1.0,
        matched_ticket_ids=[],
        mechanism_reasoning=reason,
        likely_root_cause="Unknown - no comparable history available.",
        recommended_action="Triage as a new issue; no prior incident to reference.",
        evidence_gaps=["No relevant memories were recalled from history."],
    )


def reason_about_bug(raw_bug_text: str, extraction, facts: list[RecalledFact],
                      ticket_lookup: dict[str, dict], max_candidates: int = 5) -> Verdict:
    candidate_ids = []
    for f in facts:
        if f.ticket_id and f.ticket_id in ticket_lookup and f.ticket_id not in candidate_ids:
            candidate_ids.append(f.ticket_id)
        if len(candidate_ids) >= max_candidates:
            break

    if not candidate_ids:
        return _automatic_no_match(
            "Recall returned no memories that could be mapped to a known past ticket."
        )

    candidates_text = "\n\n".join(_candidate_block(ticket_lookup[tid]) for tid in candidate_ids)

    user = f"""NEW BUG REPORT (raw):
\"\"\"
{raw_bug_text}
\"\"\"

NEW BUG (structured):
component: {extraction.component}
symptom_class: {extraction.symptom_class}
symptom_summary: {extraction.symptom_summary}
conditions: {extraction.conditions}
mechanism_hypotheses: {extraction.mechanism_hypotheses}

CANDIDATE PAST INCIDENTS FROM MEMORY (in recall order):
{candidates_text}"""

    return chat_json(REASON_SYSTEM, user, Verdict)
