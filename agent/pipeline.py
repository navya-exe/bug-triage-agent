"""
The full read path in one call: raw bug text -> Verdict.

    new bug text -> extract -> recall -> reason -> verdict

This is the single entry point the Streamlit UI (Step 7) and the write path
(Step 6) both use, so there is exactly one place that defines "how triage
works." Do not duplicate this logic elsewhere.
"""

from dataclasses import dataclass

from hindsight_client import Hindsight

from .extract import Extraction, extract_bug
from .reason import Verdict, reason_about_bug
from .recall import RecalledFact, recall_for_extraction


@dataclass
class TriageResult:
    raw_text: str
    extraction: Extraction
    facts: list[RecalledFact]
    verdict: Verdict
    error: str | None = None


def triage(client: Hindsight, bank_id: str, raw_text: str,
           ticket_lookup: dict[str, dict], min_score: float | None = None) -> TriageResult:
    raw_text = (raw_text or "").strip()
    if len(raw_text) < 15:
        # Fail fast on obviously-too-short input rather than spending an LLM
        # call on it and getting a low-quality extraction back.
        raise ValueError("Bug report is too short to triage meaningfully (need at least 15 characters).")

    extraction = extract_bug(raw_text)
    facts = recall_for_extraction(client, bank_id, extraction)
    verdict = reason_about_bug(raw_text, extraction, facts, ticket_lookup)
    return TriageResult(raw_text=raw_text, extraction=extraction, facts=facts, verdict=verdict)
