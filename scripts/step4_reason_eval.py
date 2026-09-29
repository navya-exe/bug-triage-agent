"""
Step 4: does Reason produce correct, well-justified verdicts?

Tests three groups, because a triage agent has to be right in three
different ways, not just one:
  A. The 4 held-back tickets  -> should verdict "recurrence" or
     "related_variant", citing the right family.
  B. 2 near-miss distractors  -> should verdict "no_match". These are real
     closed tickets (TICKET-5139, TICKET-5147) that share surface words with
     a family (duplicates / dates) but NOT the mechanism. If Reason matches
     these, it is pattern-matching on words, not mechanism - the core
     failure mode this whole project exists to avoid.
  C. 2 fabricated negative bugs -> should verdict "no_match" with low/no
     candidates, since nothing like them exists in history at all.

Usage (PowerShell, from project root):
    $env:GROQ_API_KEY="..."
    $env:HINDSIGHT_BANK="bugtriage-seeded"
    python scripts/step4_reason_eval.py
"""

import json
import os

from hindsight_client import Hindsight

from agent.extract import extract_bug
from agent.reason import reason_about_bug
from agent.recall import recall_for_extraction
from common import ROOT, closed_tickets, family_members, load_tickets, open_tickets, raw_query

BASE_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
BANK_ID = os.getenv("HINDSIGHT_BANK", "bugtriage-seeded")
OUT_PATH = ROOT / "data" / f"step4_reason_{BANK_ID}.json"

DISTRACTOR_IDS = ["TICKET-5139", "TICKET-5147"]

NEGATIVE_QUERIES = [
    ("neg-1", "Exported PDF invoices show a blank second page when printed from Safari on macOS"),
    ("neg-2", "Two-factor SMS codes arrive ten minutes late for customers on one mobile carrier"),
]


def run_one(client, ticket_lookup, label: str, raw_text: str, expect_no_match: bool,
            true_family: set[str]) -> dict:
    print(f"\n=== {label} ===\nraw: {raw_text}")
    extraction = extract_bug(raw_text)
    facts = recall_for_extraction(client, BANK_ID, extraction)
    verdict = reason_about_bug(raw_text, extraction, facts, ticket_lookup)

    matched = set(verdict.matched_ticket_ids)
    correct_family = bool(matched & true_family) if true_family else None
    no_hallucination = matched.issubset(set(ticket_lookup.keys()))
    passed_no_match_expectation = (verdict.verdict == "no_match") if expect_no_match else None

    print(f"verdict={verdict.verdict} confidence={verdict.confidence:.2f} matched={sorted(matched)}")
    print(f"reasoning: {verdict.mechanism_reasoning}")
    if verdict.past_fix_assessment:
        print(f"past_fix_assessment: {verdict.past_fix_assessment}")

    checks = []
    if expect_no_match:
        checks.append(("expected no_match", passed_no_match_expectation))
    elif true_family:
        checks.append(("cited a true family member", correct_family))
        checks.append(("verdict is not no_match", verdict.verdict != "no_match"))
    checks.append(("no hallucinated ticket IDs", no_hallucination))

    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    return {
        "label": label, "raw_text": raw_text,
        "extraction": extraction.model_dump(), "verdict": verdict.model_dump(),
        "checks": {name: ok for name, ok in checks},
        "all_passed": all(ok for _, ok in checks),
    }


def main() -> None:
    tickets = load_tickets()
    closed, held_out = closed_tickets(tickets), open_tickets(tickets)
    ticket_lookup = {t["ticket_id"]: t for t in closed}  # candidates come only from history
    client = Hindsight(base_url=BASE_URL)
    print(f"Server: {BASE_URL} | bank: {BANK_ID}")

    results = []

    print("\n########## GROUP A: held-back tickets (expect recurrence/related_variant) ##########")
    for h in held_out:
        family = family_members(h, closed)
        raw_text = raw_query(h, "full")
        results.append(run_one(client, ticket_lookup, h["ticket_id"], raw_text,
                                expect_no_match=False, true_family=family))

    print("\n########## GROUP B: near-miss distractors (expect no_match) ##########")
    by_id = {t["ticket_id"]: t for t in closed}
    for tid in DISTRACTOR_IDS:
        t = by_id[tid]
        raw_text = raw_query(t, "full")
        results.append(run_one(client, ticket_lookup, f"distractor-{tid}", raw_text,
                                expect_no_match=True, true_family=set()))

    print("\n########## GROUP C: fabricated negatives (expect no_match) ##########")
    for label, text in NEGATIVE_QUERIES:
        results.append(run_one(client, ticket_lookup, label, text,
                                expect_no_match=True, true_family=set()))

    OUT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    n_pass = sum(r["all_passed"] for r in results)
    print(f"\n{n_pass}/{len(results)} cases passed all checks. Saved {OUT_PATH}")
    if n_pass < len(results):
        print("Do not move to Step 5 until distractor/negative failures are understood.")
        print("A false match on a distractor is worse than a missed match on a held-back ticket:")
        print("it means Reason is pattern-matching on words, not mechanism.")


if __name__ == "__main__":
    main()
