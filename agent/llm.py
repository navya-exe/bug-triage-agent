"""
Thin Cerebras wrapper: one call in, one validated Pydantic object out.

Handles:
  1. Cerebras rate limits -> wait and retry.
  2. Malformed / non-schema JSON -> feed the error back and retry.

Environment variables:
    CEREBRAS_API_KEY       required
    LLM_MODEL              default gpt-oss-120b
    LLM_MAX_TOKENS         default 2500
    LLM_REASONING_EFFORT   optional
"""

import json
import os
import re
import time

from dotenv import load_dotenv
from cerebras.cloud.sdk import Cerebras
from pydantic import BaseModel

load_dotenv()

MODEL = os.getenv("LLM_MODEL", "gpt-oss-120b")
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2500"))
REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT")

_client: Cerebras | None = None


def _get_client() -> Cerebras:
    global _client

    if _client is None:
        _client = Cerebras(
            api_key=os.environ["CEREBRAS_API_KEY"]
        )

    return _client


def _is_rate_limit(exc: Exception) -> bool:
    s = str(exc).lower()

    return any(
        k in s
        for k in (
            "429",
            "rate limit",
            "rate_limit",
            "quota",
            "too many requests",
        )
    )


def _complete(messages: list[dict], temperature: float) -> str:
    kwargs = dict(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_completion_tokens=MAX_TOKENS,
    )

    if REASONING_EFFORT:
        kwargs["reasoning_effort"] = REASONING_EFFORT

    # Cerebras allows 5 requests/minute on this account.
    # Retry slowly rather than sending bursts.
    wait = 15

    for attempt in range(1, 6):
        try:
            response = _get_client().chat.completions.create(**kwargs)

            return response.choices[0].message.content or ""

        except Exception as exc:
            if _is_rate_limit(exc) and attempt < 5:
                print(
                    f"   [llm] rate limited; waiting "
                    f"{wait}s (attempt {attempt}/5)"
                )

                time.sleep(wait)
                wait = min(wait * 2, 120)
                continue

            raise

    return ""


def _parse_json(text: str):
    text = text.strip()

    text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        text,
        flags=re.S,
    ).strip()

    try:
        return json.loads(text)

    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)

        if not match:
            raise ValueError("no JSON object found in reply")

        return json.loads(match.group(0))


def chat_json(
    system: str,
    user: str,
    schema: type[BaseModel],
    temperature: float = 0.1,
    retries: int = 2,
):
    """Call Cerebras and return a validated Pydantic schema instance."""

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    last_error: Exception | None = None

    for _ in range(retries + 1):
        text = _complete(messages, temperature)

        try:
            return schema.model_validate(_parse_json(text))

        except ValueError as exc:
            last_error = exc

            messages += [
                {
                    "role": "assistant",
                    "content": text or "(empty reply)",
                },
                {
                    "role": "user",
                    "content": (
                        f"That reply was invalid ({str(exc)[:300]}). "
                        "Reply again with ONLY the JSON object: "
                        "no prose, no code fences."
                    ),
                },
            ]

    raise RuntimeError(
        f"LLM output failed validation after "
        f"{retries + 1} attempts: {last_error}"
    )