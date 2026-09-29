"""
LLM #1 - Extract: raw bug report -> structured description + recall query.

Design notes (from the Step 2 baseline):
  - recall_query deliberately contains NO product/feature/service names. The
    same root cause recurs in unrelated parts of the system, so those words
    are noise at best and misleading at worst (TICKET-2201 got WORSE when
    component + conditions were added).
  - mechanism_hypotheses give recall extra, differently-angled queries. They
    are guesses, so they are only used to widen recall. The Reason step (Step 4)
    decides what actually matches.
  - Prompt examples are deliberately unrelated to any mechanism in the dataset.
    Do not "improve" the prompt by adding examples that mirror the dataset's
    root-cause families: that would leak the answer key into the extractor.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .llm import chat_json

_CLASS_ALIASES = {
    "performance": "perf",
    "slow": "perf",
    "slowdown": "perf",
    "incorrect-output": "wrong-output",
    "wrong-result": "wrong-output",
    "freeze": "hang",
    "timeout": "hang",
    "flaky": "intermittent",
}


class Extraction(BaseModel):
    component: str | None = None
    symptom_class: Literal["crash", "hang", "wrong-output", "perf", "intermittent"]
    symptom_summary: str
    conditions: str | None = None
    frequency_pattern: str | None = None
    mechanism_hypotheses: list[str] = Field(default_factory=list)
    recall_query: str = Field(min_length=10)

    @field_validator("symptom_class", mode="before")
    @classmethod
    def _normalize_class(cls, v):
        v = str(v).strip().lower().replace("_", "-").replace(" ", "-")
        return _CLASS_ALIASES.get(v, v)

    @field_validator("mechanism_hypotheses")
    @classmethod
    def _clip_hypotheses(cls, v):
        return [h.strip() for h in v if h and h.strip()][:3]


EXTRACT_SYSTEM = """You are a bug-report analyst on an engineering team. Convert the raw bug report into structured JSON. You do NOT decide whether this bug is new or a repeat of an old one. You only describe what the report says and what kind of failure it looks like.

Rules:
- Use only information in the report. Use null when something is not stated. Never invent details.
- symptom_class must be exactly one of: crash | hang | wrong-output | perf | intermittent
- conditions: environment, load, timing, device, user segment, frequency, or anything that seems to trigger the problem.
- mechanism_hypotheses: up to 3 SHORT, general software failure mechanisms that could plausibly produce this behavior. Style examples only (do not copy them): "N+1 query pattern", "lock contention", "integer overflow", "floating-point rounding". Choose whatever fits THIS report. Use an empty list if the report gives no basis. These are guesses, not conclusions.
- recall_query: 1-2 sentences describing the failure PATTERN, written to search a history of past incidents. Say what fails, under what conditions, and how it behaves over time. Do NOT include product, feature, screen, or service names: past incidents with the same cause often happened in completely different parts of the system.

Return ONLY a JSON object with exactly these keys, with no markdown fences and no commentary:
{"component": string|null, "symptom_class": string, "symptom_summary": string, "conditions": string|null, "frequency_pattern": string|null, "mechanism_hypotheses": [string], "recall_query": string}"""


def extract_bug(raw_text: str) -> Extraction:
    """Run LLM #1 on a raw bug report and return a validated Extraction."""
    user = f'BUG REPORT:\n"""\n{raw_text}\n"""'
    return chat_json(EXTRACT_SYSTEM, user, Extraction)
