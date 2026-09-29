"""
Streamlit demo UI.

Run from project root:
    streamlit run app.py

Two panels:
  - Left: paste a bug report, hit Triage.
  - Right: the verdict, and if a match was found, a side-by-side card
    showing the new report next to the matched historical ticket. This card
    is the whole demo payoff - the judge should be able to SEE the
    connection, not just read a paragraph asserting it.
"""

import os

import streamlit as st
from hindsight_client import Hindsight

from agent.pipeline import triage
from scripts.common import closed_tickets, load_tickets

st.set_page_config(page_title="Bug Triage Memory Agent", layout="wide")

BANK_ID = os.getenv("HINDSIGHT_BANK", "bugtriage-seeded")
BASE_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")


@st.cache_resource
def get_client() -> Hindsight:
    return Hindsight(
    base_url=BASE_URL,
    api_key=os.environ["HINDSIGHT_API_KEY"],
)


@st.cache_data
def get_ticket_lookup() -> dict[str, dict]:
    return {t["ticket_id"]: t for t in closed_tickets(load_tickets())}


VERDICT_STYLE = {
    "recurrence": ("🔴", "Likely recurrence"),
    "related_variant": ("🟡", "Possibly related"),
    "no_match": ("🟢", "No relevant history found"),
}


def render_ticket_card(title: str, ticket: dict | None, raw_text: str | None = None) -> None:
    st.markdown(f"**{title}**")
    if ticket is None:
        st.info(raw_text or "No data")
        return
    st.markdown(f"`{ticket['ticket_id']}` · {ticket['component']} · {ticket['symptom_class']}")
    st.write(ticket["symptom_text"])
    st.caption(f"Conditions: {ticket['conditions']}")
    st.markdown(f"**Root cause:** {ticket['root_cause']}")
    fix_badge = "⚠️ workaround" if ticket["fix_type"] == "workaround" else "✅ real fix"
    st.markdown(f"**Fix:** {ticket['fix_applied']}  \n{fix_badge}")


def main() -> None:
    st.title("🐛 Bug Triage Memory Agent")
    st.caption(f"Hindsight bank: `{BANK_ID}`")

    ticket_lookup = get_ticket_lookup()
    client = get_client()

    raw_text = st.text_area(
        "Paste a new bug report",
        height=140,
        placeholder="e.g. wishlist-service: tapping 'Save for later' once on mobile created two identical entries...",
    )
    run = st.button("Triage", type="primary")

    if not run:
        st.caption(f"Memory currently holds {len(ticket_lookup)} resolved tickets.")
        return

    if len(raw_text.strip()) < 15:
        st.warning("Bug report is too short to triage meaningfully.")
        return

    with st.spinner("Extracting → recalling → reasoning..."):
        try:
            result = triage(client, BANK_ID, raw_text, ticket_lookup)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Triage failed: {exc}")
            return

    v = result.verdict
    icon, label = VERDICT_STYLE[v.verdict]
    st.subheader(f"{icon} {label}  ·  confidence {v.confidence:.0%}")
    st.write(v.mechanism_reasoning)

    if v.past_fix_assessment:
        st.markdown(f"**Past fix assessment:** {v.past_fix_assessment}")
    st.markdown(f"**Recommended action:** {v.recommended_action}")
    if v.evidence_gaps:
        st.caption("Evidence gaps: " + "; ".join(v.evidence_gaps))

    if v.matched_ticket_ids:
        st.divider()
        st.markdown("### The match")
        for tid in v.matched_ticket_ids:
            left, right = st.columns(2)
            with left:
                render_ticket_card("New bug (just submitted)", None, raw_text)
            with right:
                render_ticket_card(f"Past incident — {tid}", ticket_lookup.get(tid))

    with st.expander("Show extraction + raw verdict JSON"):
        st.json(result.extraction.model_dump())
        st.json(v.model_dump())


if __name__ == "__main__":
    main()
