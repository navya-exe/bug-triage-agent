"""
Recall layer: structured extraction -> Hindsight -> mapped past incidents.

Hindsight is responsible for finding relevant memories.
This module only converts Hindsight results into a small, stable structure
that the Reason step can consume.
"""

import json
import re
from dataclasses import dataclass

from hindsight_client import Hindsight

from .extract import Extraction


TICKET_ID_RE = re.compile(r"TICKET-\d{4}")


@dataclass
class RecalledFact:
    ticket_id: str | None
    text: str
    score: float | None = None


def _dump_result(result) -> str:
    """Serialize a Hindsight result so ticket IDs can be extracted robustly."""
    for name in ("model_dump", "dict"):
        fn = getattr(result, name, None)
        if callable(fn):
            try:
                return json.dumps(fn(), default=str)
            except Exception:
                pass

    try:
        return json.dumps(vars(result), default=str)
    except Exception:
        return repr(result)


def _result_text(result) -> str:
    """Get the human-readable text from a Hindsight result."""
    text = getattr(result, "text", None)

    if text:
        return str(text)

    return _dump_result(result)


def _result_score(result) -> float | None:
    """Read a score if the installed Hindsight client exposes one."""
    for name in ("score", "final_score"):
        value = getattr(result, name, None)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass

    return None


def _extract_ticket_id(result) -> str | None:
    """Find the first TICKET-#### reference in a recalled result."""
    matches = TICKET_ID_RE.findall(_dump_result(result))
    return matches[0] if matches else None


def _recall_one(
    client: Hindsight,
    bank_id: str,
    query: str,
):
    """Run one Hindsight recall query without applying a score threshold."""
    return client.recall(
        bank_id=bank_id,
        query=query,
    )


def recall_for_extraction(
    client: Hindsight,
    bank_id: str,
    extraction: Extraction,
    max_facts: int = 10,
) -> list[RecalledFact]:
    """
    Recall past incidents using the extractor's main query plus
    mechanism hypotheses.

    The hypotheses widen recall; they do NOT decide whether a bug is a match.
    The Reason step makes that decision.
    """

    queries = [extraction.recall_query]

    for hypothesis in extraction.mechanism_hypotheses:
        if hypothesis.strip():
            queries.append(hypothesis.strip())

    recalled: list[RecalledFact] = []
    seen_ticket_ids: set[str] = set()

    for query in queries:
        results = _recall_one(client, bank_id, query)

        for result in results.results:
            ticket_id = _extract_ticket_id(result)

            # Keep unmapped facts too, but don't let duplicate ticket IDs
            # flood the candidate list.
            if ticket_id and ticket_id in seen_ticket_ids:
                continue

            if ticket_id:
                seen_ticket_ids.add(ticket_id)

            recalled.append(
                RecalledFact(
                    ticket_id=ticket_id,
                    text=_result_text(result),
                    score=_result_score(result),
                )
            )

            if len(recalled) >= max_facts:
                return recalled

    return recalled