"""
Step 2b: baseline. Raw recall against the seeded bank with NO extraction and
NO reasoning. This is the "before" number that Extract + Reason must beat.

For each held-back (open) ticket we ask: do tickets from the correct
root-cause family appear in the top results, and at what rank?

Usage (from project root, PowerShell):
    $env:HINDSIGHT_BANK="bugtriage-seeded"
    python scripts/step2_baseline.py

Set BLIND=1 to target the blind bank (bugtriage-seeded-blind).
Writes data/baseline_<bank>.json so you can compare later runs.
"""

import json
import os

from hindsight_client import Hindsight

from common import (
    ROOT,
    TICKET_ID_RE,
    closed_tickets,
    family_members,
    load_tickets,
    open_tickets,
    raw_query,
)

BASE_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
BLIND = os.getenv("BLIND", "0") == "1"
BANK_ID = os.getenv("HINDSIGHT_BANK", "bugtriage-seeded-blind" if BLIND else "bugtriage-seeded")

THRESHOLDS = [None, 0.3, 0.5]          # None = no min_scores at all
VARIANTS = ["symptom_only", "full"]
TOP_N = 5

# Fresh bugs with NO counterpart in the dataset: recall should find nothing useful.
NEGATIVE_QUERIES = [
    "Exported PDF invoices show a blank second page when printed from Safari on macOS",
    "Two-factor SMS codes arrive ten minutes late for customers on one mobile carrier",
]


def dump(r) -> str:
    """Serialize a recall result without knowing its exact class/fields."""
    for name in ("model_dump", "dict"):
        fn = getattr(r, name, None)
        if callable(fn):
            try:
                return json.dumps(fn(), default=str)
            except Exception:  # noqa: BLE001
                pass
    try:
        return json.dumps(vars(r), default=str)
    except Exception:  # noqa: BLE001
        return repr(r)


def do_recall(client: Hindsight, query: str, threshold: float | None):
    kwargs = {"bank_id": BANK_ID, "query": query}
    if threshold is not None:
        kwargs["min_scores"] = {"final": threshold}
    return client.recall(**kwargs)


def ranked_ticket_ids(results) -> tuple[list[str], int]:
    """Distinct ticket IDs in order of first appearance, plus count of facts
    where no ticket ID could be found anywhere in the result object."""
    seen: set[str] = set()
    order: list[str] = []
    unmapped = 0
    for r in results.results:
        ids = TICKET_ID_RE.findall(dump(r))
        if not ids:
            unmapped += 1
            continue
        for tid in ids:
            if tid not in seen:
                seen.add(tid)
                order.append(tid)
    return order, unmapped


def main() -> None:
    tickets = load_tickets()
    closed, held_out = closed_tickets(tickets), open_tickets(tickets)
    client = Hindsight(base_url=BASE_URL)
    print(f"Server: {BASE_URL} | bank: {BANK_ID} | blind: {BLIND}\n")

    # One-time look at what a recall result really contains.
    probe = do_recall(client, raw_query(held_out[0], "full"), None)
    if probe.results:
        print("Example result object (truncated):")
        print("  ", dump(probe.results[0])[:600], "\n")
    else:
        print("Probe recall returned nothing. Is the bank seeded?\n")

    rows = []
    print("=== HELD-BACK TICKETS ===")
    for h in held_out:
        family = family_members(h, closed)
        print(f"\n{h['ticket_id']} ({h['component']}) | true family: {sorted(family)}")
        for variant in VARIANTS:
            query = raw_query(h, variant)
            for thr in THRESHOLDS:
                res = do_recall(client, query, thr)
                order, unmapped = ranked_ticket_ids(res)
                top = order[:TOP_N]
                hits = [tid for tid in top if tid in family]
                first = next((i + 1 for i, tid in enumerate(order) if tid in family), None)
                row = {
                    "ticket": h["ticket_id"], "variant": variant, "threshold": thr,
                    "n_facts": len(res.results), "family_hits_top_n": len(hits),
                    "family_size": len(family), "first_family_rank": first,
                    "top": top, "unmapped_facts": unmapped,
                }
                rows.append(row)
                print(
                    f"  {variant:12} thr={str(thr):4} | hits in top {TOP_N}: {len(hits)}/{len(family)}"
                    f" | first family rank: {first} | top: {top} | unmapped: {unmapped}"
                )

    print("\n=== NEGATIVE QUERIES (nothing relevant exists) ===")
    for q in NEGATIVE_QUERIES:
        print(f"\nQ: {q}")
        for thr in THRESHOLDS:
            res = do_recall(client, q, thr)
            order, _ = ranked_ticket_ids(res)
            print(f"  thr={str(thr):4} | facts returned: {len(res.results)} | tickets: {order[:TOP_N]}")
            rows.append({"negative": q, "threshold": thr, "n_facts": len(res.results), "top": order[:TOP_N]})

    out = ROOT / "data" / f"baseline_{BANK_ID}.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")

    if all(r.get("unmapped_facts", 0) and not r.get("top") for r in rows if "ticket" in r):
        print("\nWARNING: no ticket IDs could be mapped from recall results. Ticket IDs are not "
              "surviving into recalled facts. See the fix options in the Step 2 notes.")


if __name__ == "__main__":
    main()
