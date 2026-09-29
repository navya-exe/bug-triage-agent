import json

from agent.extract import extract_bug
from scripts.common import load_tickets


TEST_TICKET_IDS = [
    "TICKET-1031",
    "TICKET-2201",
    "TICKET-3142",
    "TICKET-4132",
]


def main():
    results = {}
    tickets = load_tickets()
    by_id = {t["ticket_id"]: t for t in tickets}

    for ticket_id in TEST_TICKET_IDS:
        ticket = by_id[ticket_id]

        raw_text = (
    f"Component: {ticket.get('component', '')}\n"
    f"Symptom: {ticket.get('symptom_text', '')}\n"
    f"Conditions: {ticket.get('conditions', '')}"
)

        print("=" * 80)
        print(ticket_id)
        print("=" * 80)

        result = extract_bug(raw_text)
        results[ticket_id] = result.model_dump()

        print(json.dumps(result.model_dump(), indent=2))

    with open("data/step3_extractions.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()