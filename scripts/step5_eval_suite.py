"""
Step 5: run the SAME test suite as Step 4, but through the assembled
triage() pipeline, not the individual pieces. This is your regression test:
if this ever fails after you touch prompts or code, something broke.

Also produces a clean pass/fail table you can paste into your README as
evidence, and times each call so you know your live-demo latency budget.

Usage:
    $env:GROQ_API_KEY="..."
    $env:HINDSIGHT_BANK="bugtriage-seeded"
    python scripts/step5_eval_suite.py
"""

import json
import os
import time

from hindsight_client import Hindsight

from agent.pipeline import triage
from common import ROOT, closed_tickets, family_members, load_tickets, open_tickets, raw_query

BASE_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
BANK_ID = os.getenv("HINDSIGHT_BANK", "bugtriage-seeded")
OUT_PATH = ROOT / "data" / f"step5_eval_{BANK_ID}.json"

DISTRACTOR_IDS = ["TICKET-5139", "TICKET-5147"]
NEGATIVE_QUERIES = [
    ("neg-1", "Exported PDF invoices show a blank second page when printed from Safari on macOS"),
    ("neg-2", "Two-factor SMS codes arrive ten minutes late for customers on one mobile carrier"),
]


def check(label, raw_text, expect_no_match, true_family, client, ticket_lookup):
    started = time.time()
    try:
        result = triage(client, BANK_ID, raw_text, ticket_lookup)
    except Exception as exc:  # noqa: BLE001
        return {"label": label, "error": str(exc), "all_passed": False, "elapsed_s": time.time() - started}
    elapsed = time.time() - started

    v = result.verdict
    matched = set(v.matched_ticket_ids)
    checks = {"no_hallucinated_ids": matched.issubset(set(ticket_lookup.keys()))}
    if expect_no_match:
        checks["expected_no_match"] = v.verdict == "no_match"
    else:
        checks["cited_true_family_member"] = bool(matched & true_family)
        checks["not_no_match"] = v.verdict != "no_match"

    passed = all(checks.values())
    print(f"[{'PASS' if passed else 'FAIL'}] {label:22} verdict={v.verdict:15} "
          f"conf={v.confidence:.2f} matched={str(sorted(matched)):20} ({elapsed:.1f}s)")
    return {
        "label": label, "verdict": v.model_dump(), "checks": checks,
        "all_passed": passed, "elapsed_s": round(elapsed, 1),
    }


def main() -> None:
    tickets = load_tickets()
    closed, held_out = closed_tickets(tickets), open_tickets(tickets)
    ticket_lookup = {t["ticket_id"]: t for t in closed}
    by_id = {t["ticket_id"]: t for t in closed}
    client = Hindsight(base_url=BASE_URL)
    print(f"Server: {BASE_URL} | bank: {BANK_ID}\n")

    rows = []
    for h in held_out:
        rows.append(check(h["ticket_id"], raw_query(h, "full"), False,
                           family_members(h, closed), client, ticket_lookup))
    for tid in DISTRACTOR_IDS:
        rows.append(check(f"distractor-{tid}", raw_query(by_id[tid], "full"), True,
                           set(), client, ticket_lookup))
    for label, text in NEGATIVE_QUERIES:
        rows.append(check(label, text, True, set(), client, ticket_lookup))

    n_pass = sum(r["all_passed"] for r in rows)
    avg_time = sum(r.get("elapsed_s", 0) for r in rows) / len(rows)
    print(f"\n{n_pass}/{len(rows)} passed. Average latency: {avg_time:.1f}s per triage call.")
    print("If average latency is high, budget for it live during the demo, or pre-run and cache results.")

    OUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Saved {OUT_PATH}")


if __name__ == "__main__":
    main()
