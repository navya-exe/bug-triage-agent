"""
Step 2a: retain every CLOSED ticket into a Hindsight bank.

Design goals (driven by what happened in Step 1):
  - Throttled: Groq's tokens-per-minute limit rejected back-to-back retains.
  - Resumable: a manifest records which tickets succeeded; re-running skips them.
  - Traceable: ticket ID goes in the content, the context string, and (if the
    installed client supports it) document_id, so recall results can be mapped
    back to tickets.

Usage (from project root, PowerShell):
    $env:HINDSIGHT_BANK="bugtriage-seeded"
    python scripts/step2_seed.py

Optional env vars:
    BLIND=1            seed a harder variant (no cross-references / lessons);
                       default bank becomes bugtriage-seeded-blind
    SLEEP_BETWEEN=45   seconds to wait between successful retains
    MAX_RETRIES=5      retries per ticket on rate-limit errors
    HINDSIGHT_URL      default http://localhost:8888
"""

import inspect
import json
import os
import sys
import time

from hindsight_client import Hindsight

from common import ROOT, closed_tickets, load_tickets, ticket_to_prose

BASE_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
BLIND = os.getenv("BLIND", "0") == "1"
BANK_ID = os.getenv("HINDSIGHT_BANK", "bugtriage-seeded-blind" if BLIND else "bugtriage-seeded")
SLEEP_BETWEEN = float(os.getenv("SLEEP_BETWEEN", "45"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
MANIFEST = ROOT / "data" / f"retained_{BANK_ID}.json"


def load_manifest() -> set[str]:
    if MANIFEST.exists():
        return set(json.loads(MANIFEST.read_text(encoding="utf-8")))
    return set()


def save_manifest(done: set[str]) -> None:
    MANIFEST.write_text(json.dumps(sorted(done), indent=2), encoding="utf-8")


def is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(k in s for k in ("429", "rate limit", "quota", "tokens per minute"))


def retain_one(client: Hindsight, supported: set[str], t: dict) -> bool:
    kwargs = dict(
        bank_id=BANK_ID,
        content=ticket_to_prose(t, blind=BLIND),
        context=f"Resolved bug post-mortem for {t['ticket_id']}",
        timestamp=f"{t['date']}T09:00:00Z",
    )
    # Only pass optional params if this client version actually has them.
    if "document_id" in supported:
        kwargs["document_id"] = t["ticket_id"]

    wait = 30
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client.retain(**kwargs)
            return True
        except Exception as exc:  # noqa: BLE001
            if is_rate_limit(exc) and attempt < MAX_RETRIES:
                print(f"   rate limited (attempt {attempt}/{MAX_RETRIES}); waiting {wait}s")
                time.sleep(wait)
                wait = min(wait * 2, 180)
                continue
            print(f"   FAILED {t['ticket_id']}: {exc}")
            return False
    return False


def main() -> None:
    tickets = closed_tickets(load_tickets())
    client = Hindsight(
    base_url=BASE_URL,
    api_key=os.environ["HINDSIGHT_API_KEY"],
)

    supported = set(inspect.signature(Hindsight.retain).parameters)
    print(f"Server: {BASE_URL} | bank: {BANK_ID} | blind: {BLIND}")
    print(f"retain() parameters on this client: {sorted(supported - {'self'})}")

    done = load_manifest()
    pending = [t for t in tickets if t["ticket_id"] not in done]
    print(f"{len(tickets)} closed tickets | {len(done)} already retained | {len(pending)} to go\n")

    failed: list[str] = []
    for i, t in enumerate(pending, 1):
        started = time.time()
        print(f"[{i}/{len(pending)}] retaining {t['ticket_id']} ({t['component']})")
        if retain_one(client, supported, t):
            done.add(t["ticket_id"])
            save_manifest(done)
            print(f"   ok in {time.time() - started:.1f}s")
            if i < len(pending):
                time.sleep(SLEEP_BETWEEN)
        else:
            failed.append(t["ticket_id"])

    print(f"\nRetained {len(done)}/{len(tickets)}. Failed: {failed or 'none'}")
    if failed:
        print("Re-run the same command to retry only the failed tickets.")
        sys.exit(1)


if __name__ == "__main__":
    main()
