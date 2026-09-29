"""
Step 6: prove the loop closes. Triage a held-back ticket (memory doesn't
have it yet) -> resolve it (extract + retain) -> triage a THIRD occurrence
of the same family that isn't in the dataset at all -> show it gets caught,
now citing the ticket we just retained live.

This is your strongest visual for the "agent gets smarter over time" claim,
because the third-occurrence ticket exists nowhere in your seed data - the
agent can only catch it because of what THIS script just taught it.

Usage:
    $env:GROQ_API_KEY="..."
    $env:HINDSIGHT_BANK="bugtriage-seeded"
    python scripts/step6_write_path_demo.py
"""

import os

from hindsight_client import Hindsight

from agent.pipeline import triage
from agent.retain_resolution import retain_resolution
from common import ROOT, closed_tickets, family_members, load_tickets, open_tickets, raw_query

BASE_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
BANK_ID = os.getenv("HINDSIGHT_BANK", "bugtriage-seeded")

# Held-back ticket to resolve live. Swap for TICKET-2201/3142/4132 if you'd
# rather demo a different family.
TICKET_TO_RESOLVE = "TICKET-1031"

# Written by hand, deliberately NOT phrased like the dataset's existing
# tickets, and describing a fourth surface location for the SAME mechanism
# (checkout hang -> duplicate order -> duplicate auth -> duplicate cart add
# -> now: duplicate wishlist entry). Nothing in the seed data mentions this.
THIRD_OCCURRENCE_TEXT = (
    "wishlist-service: a customer says that tapping 'Save for later' once on "
    "their phone, on a slow connection, created two identical entries in "
    "their wishlist. Only happens on mobile, hasn't been reproduced on desktop."
)


def main() -> None:
    tickets = load_tickets()
    closed, held_out = closed_tickets(tickets), open_tickets(tickets)
    ticket_lookup = {t["ticket_id"]: t for t in closed}
    client = Hindsight(base_url=BASE_URL)
    to_resolve = next(t for t in held_out if t["ticket_id"] == TICKET_TO_RESOLVE)

    print(f"Server: {BASE_URL} | bank: {BANK_ID}\n")

    # --- 1. Triage BEFORE resolving (memory doesn't have this ticket yet) ---
    print(f"### 1. Triage {TICKET_TO_RESOLVE} before it's in memory ###")
    raw_text = raw_query(to_resolve, "full")
    before = triage(client, BANK_ID, raw_text, ticket_lookup)
    print(f"verdict={before.verdict.verdict} matched={before.verdict.matched_ticket_ids}\n")

    # --- 2. Resolve it: extract root cause/fix + retain ---
    print(f"### 2. Resolve {TICKET_TO_RESOLVE} and retain the outcome ###")
    resolution_notes = (
        "Traced to the same click-handler debounce race as prior incidents. "
        "Backend idempotency checks only cover orders and payments, not the "
        "cart-add endpoint, so the race still slips through there. Added a "
        "matching idempotency check to the cart-add endpoint as a stopgap; "
        "the frontend debounce logic itself is still not fixed at the source."
    )
    mem = retain_resolution(
        client, BANK_ID, TICKET_TO_RESOLVE, to_resolve["component"],
        to_resolve["symptom_class"], raw_text, resolution_notes,
        date_iso=f"{to_resolve['date']}T09:00:00Z",
    )
    print(f"retained: fix_type={mem.fix_type} | root_cause={mem.root_cause}\n")
    # Ticket-level lookup needs this new record too, so future triage calls
    # (including the one below) can show it in the side-by-side card.
    ticket_lookup[TICKET_TO_RESOLVE] = {
        "ticket_id": TICKET_TO_RESOLVE, "component": to_resolve["component"],
        "symptom_class": to_resolve["symptom_class"], "symptom_text": to_resolve["symptom_text"],
        "conditions": to_resolve["conditions"], "root_cause": mem.root_cause,
        "fix_applied": mem.fix_applied, "fix_type": mem.fix_type,
    }

    # --- 3. Triage a brand-new, never-seen third occurrence ---
    print("### 3. Triage a THIRD occurrence not present anywhere in the seed data ###")
    print(f"new report: {THIRD_OCCURRENCE_TEXT}\n")
    after = triage(client, BANK_ID, THIRD_OCCURRENCE_TEXT, ticket_lookup)
    print(f"verdict={after.verdict.verdict} confidence={after.verdict.confidence:.2f}")
    print(f"matched={after.verdict.matched_ticket_ids}")
    print(f"reasoning: {after.verdict.mechanism_reasoning}")

    if TICKET_TO_RESOLVE in after.verdict.matched_ticket_ids:
        print(f"\nDEMO MOMENT CONFIRMED: the agent cited {TICKET_TO_RESOLVE}, which it only")
        print("learned about a few seconds ago in step 2 of this very script.")
    else:
        print("\nDid not cite the just-retained ticket. Try a different THIRD_OCCURRENCE_TEXT")
        print("or resolve a different family (change TICKET_TO_RESOLVE).")


if __name__ == "__main__":
    main()
