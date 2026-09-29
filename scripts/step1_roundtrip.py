"""
Step 1: prove the Hindsight round trip (retain -> recall) works.

Place this file at  scripts/step1_roundtrip.py  in your project and run from
the project root:

    python scripts/step1_roundtrip.py

Prerequisites:
  - Hindsight server running locally (Docker, port 8888)
  - data/bug_tickets_dataset.json present
  - pip install hindsight-client

NOTE: written against the documented client API (retain / recall). Verify the
recall response fields against the current Hindsight docs if anything errors.
"""

import json
import os
import sys
import time
from pathlib import Path

from hindsight_client import Hindsight

BASE_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
# Use a throwaway bank for experiments so it never pollutes your real demo banks.
BANK_ID = os.getenv("HINDSIGHT_BANK", "bugtriage-step1-test")
# Retain runs an LLM extraction server-side; give it a moment before recalling.
SETTLE_SECONDS = float(os.getenv("SETTLE_SECONDS", "3"))

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "bug_tickets_dataset.json"

# Two tickets from the same root-cause family + one unrelated control.
TICKETS_TO_RETAIN = ["TICKET-5001"]
# (query, what you expect to see)
TEST_QUERIES = [
    ("customers charged twice for one order", "TICKET-1042 (maybe 1001)"),
    ("button spins forever on iPhone checkout", "TICKET-1001"),
    ("password reset emails going to spam", "TICKET-5001"),
    ("database connection pool exhaustion", "nothing relevant (not retained)"),
]


def ticket_to_prose(t: dict) -> str:
    """Turn a structured ticket into readable prose.

    Hindsight extracts facts from text, so readable sentences that keep the
    ticket ID, mechanism, and fix type tend to work better than raw JSON.
    """
    lines = [
        f"Bug {t['ticket_id']} in {t['component']}, reported {t['date']} by {t['reporter']}.",
        f"Symptom ({t['symptom_class']}): {t['symptom_text']}",
        f"Conditions: {t['conditions']}.",
        f"Root cause: {t['root_cause']}",
        f"Fix applied: {t['fix_applied']}",
        f"Fix type: {t['fix_type']}. Status: {t['status']}.",
    ]
    if t.get("reopened_from"):
        lines.append(f"This ticket followed up on or reopened {t['reopened_from']}.")
    if t.get("lesson_note"):
        lines.append(f"Lesson: {t['lesson_note']}")
    return "\n".join(lines)


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    by_id = {t["ticket_id"]: t for t in data["tickets"]}

    client = Hindsight(base_url=BASE_URL)
    print(f"Server: {BASE_URL} | bank: {BANK_ID}\n")

    # ---- RETAIN ----
    for tid in TICKETS_TO_RETAIN:
        t = by_id[tid]
        content = ticket_to_prose(t)
        started = time.time()
        try:
            client.retain(
                bank_id=BANK_ID,
                content=content,
                context="resolved bug post-mortem",
                timestamp=f"{t['date']}T09:00:00Z",
            )
        except Exception as exc:  # noqa: BLE001 - we want to see any failure here
            print(f"RETAIN FAILED for {tid}: {exc}")
            print("Check: is the Docker container running? Is the LLM API key valid?")
            sys.exit(1)
        print(f"retained {tid} in {time.time() - started:.1f}s")

    print(f"\nWaiting {SETTLE_SECONDS}s for processing...")
    time.sleep(SETTLE_SECONDS)

    # ---- RECALL ----
    print("\n--- recall tests ---")
    for query, expected in TEST_QUERIES:
        results = client.recall(
    bank_id=BANK_ID,
    query=query,
    min_scores={"final": 0.5},
)
        print(f"\nQ: {query}")
        print(f"   expected: {expected}")
        if not results.results:
            print("   (no results)")
            continue
        for i, r in enumerate(results.results[:5], 1):
            print(f"   {i}. score={getattr(r, 'score', 'N/A')} | {r.text[:200]}")


if __name__ == "__main__":
    main()