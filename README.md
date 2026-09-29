# Bug Triage Memory Agent

An agent that triages new bug reports by recalling past incidents at the **root-cause mechanism** level — even when the symptoms look unrelated — and flags when a past "fix" was really just a workaround.

## The problem

Software teams accumulate bug reports over time, but each ticket is usually treated as an isolated event. The useful causal knowledge produced during resolution — root causes, fixes, workarounds, and lessons from previous incidents — is easy to lose when engineers face the next incident.

This project treats incident history as persistent agent memory. The system recalls prior incidents by failure mechanism rather than relying on exact symptom wording, then reasons over the recalled candidates to decide whether a new bug is a recurrence, a related variant, or genuinely new. This follows the incident-response use case in the problem statement: remembering past incidents, their root causes, resolution steps, and what worked before.

## Architecture

```text
READ PATH (triage)                              WRITE PATH (learning)

┌──────────────────────┐                        ┌──────────────────────┐
│ New Bug Report       │                        │ Bug Resolved         │
└──────────┬───────────┘                        └──────────┬───────────┘
           │                                               │
           ▼                                               ▼
┌──────────────────────┐                        ┌──────────────────────┐
│ EXTRACT (LLM #1)     │                        │ EXTRACT (LLM)        │
│ failure pattern      │                        │ root cause + fix     │
│ + recall query       │                        │ + mechanism tags     │
└──────────┬───────────┘                        └──────────┬───────────┘
           │                                               │
           ▼                                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            HINDSIGHT                                │
│       RECALL ◀────────── persistent memory ────────── RETAIN        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ REASON (LLM #2)      │
                    │ mechanism comparison │
                    │ + fix assessment     │
                    └──────────┬───────────┘
                               │
                               ▼
                  recurrence / related_variant / no_match
                               │
                               ▼
                         Engineer resolves
                               │
                               └──────────→ WRITE PATH
```

Why two LLM calls instead of one: extraction and reasoning are separate stages so recall queries by **mechanism** rather than raw ticket text. The extractor produces a normalized failure description and a mechanism-phrased recall query. Hindsight retrieves candidate memories. The reasoning model then compares the new bug with those candidates and decides whether the underlying mechanism is actually shared.

## How Hindsight is used

Hindsight is the **only persistent memory layer** in the application. There is no custom vector database and no separate metadata database.

### Retain

A resolved bug is converted into a short natural-language post-mortem containing:

- ticket ID and component
- symptom and conditions
- root cause
- fix applied
- `fix_type`: `real_fix`, `workaround`, or `unknown`
- mechanism tags and an optional lesson

The write path is implemented in `agent/retain_resolution.py`. Its resolution extractor explicitly distinguishes a real fix from a workaround: a workaround suppresses the symptom while the underlying mechanism remains.

The initial history is seeded from the 28 closed tickets in `data/bug_tickets_dataset.json` using `scripts/step2_seed.py`.

### Recall

For a new bug, LLM #1 produces a mechanism-oriented `recall_query` plus up to three mechanism hypotheses. `agent/recall.py` sends those mechanism-oriented queries to Hindsight rather than sending the raw ticket text directly.

Recall results are mapped back to known ticket IDs. LLM #2 receives only those mapped candidates and the new bug's extraction, then performs the mechanism-level comparison.

### Why this matters

A symptom such as "duplicate order" can be caused by many unrelated bugs. Conversely, the same race condition can appear as a checkout hang, duplicate order, duplicate authorization, duplicate cart item, or duplicate wishlist entry. The system therefore uses Hindsight to preserve causal history and uses the reasoning stage to distinguish shared mechanisms from superficial word overlap.

## Evidence

The evaluation set contains four held-back tickets, two distractor tickets, and two fabricated negative cases.

| Stage | Result |
|---|---|
| Step 2 seed | 28 closed tickets retained in `bugtriage-seeded` |
| Step 3 extraction | 4/4 held-out tickets produced structured extraction records; the script did not emit a separate aggregate pass/fail score |
| Step 4 reasoning | 4/8 passed in the last completed run before the final prompt refinement; failures included the two self-matching distractor cases and one false-positive negative |
| Step 5 full pipeline | **6/8 passed** |
| Step 5 latency | **17.1s average per triage call** |
| Step 5 negative cases | **2/2 passed** |
| Step 6 memory-compounding demo | Newly retained `TICKET-1031` was cited for the unseen wishlist occurrence |

The Step 5 suite is the final regression measurement because it evaluates the assembled `triage()` pipeline rather than the individual components.

### Step 6: memory compounds

The strongest end-to-end demonstration is:

```text
1. Triage TICKET-1031
2. Resolve it and retain the resolution in Hindsight
3. Submit a new wishlist bug that does not exist in the seed dataset
4. The agent recalls the newly retained TICKET-1031
5. Verdict: recurrence, confidence 0.86
6. matched=['TICKET-1031', 'TICKET-1042', 'TICKET-1108']
```

The final match is not hard-coded into the demo script: the newly retained ticket becomes available through Hindsight recall and is then cited by the reasoning stage.

## Dataset and evaluation design

The original local dataset contains held-back tickets:

- `TICKET-1031`
- `TICKET-2201`
- `TICKET-3142`
- `TICKET-4132`

Two additional tickets are used as distractors:

- `TICKET-5139`
- `TICKET-5147`

The internal `family_tag` field is used only for development-time scoring and is not retained as memory or shown to the reasoning model. The held-out tickets are also stripped of `lesson_note` and `family_tag` when used as new-bug inputs.

The Step 5 evaluator checks:

1. no hallucinated ticket IDs;
2. a true family member is cited for held-out recurrence cases;
3. recurrence/related-variant is not incorrectly returned as `no_match`;
4. fabricated negative cases return `no_match`.

The two distractor cases are intentionally difficult because they are real historical tickets. A distractor can expose superficial matching even when surface words overlap. The final Step 5 run still recorded those two distractor self-matches as failures, so they should not be presented as perfect discrimination.

## Setup

### 1. Start Hindsight

The validated local setup uses self-hosted Hindsight on Docker with persistent storage:

```powershell
docker run --rm -it --pull always -p 8888:8888 -p 9999:9999 `
  -e HINDSIGHT_API_LLM_PROVIDER=groq `
  -e HINDSIGHT_API_LLM_API_KEY=$env:GROQ_API_KEY `
  -e HINDSIGHT_API_LLM_MODEL=openai/gpt-oss-120b `
  -v ${HOME}/.hindsight-docker:/home/hindsight/.pg0 `
  ghcr.io/vectorize-io/hindsight:latest
```

Keep this container running. Hindsight serves its API on `localhost:8888` and its UI on `localhost:9999`.

### 2. Install Python dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure the application LLM

The application extraction/reasoning wrapper uses Cerebras with the same `gpt-oss-120b` model:

```powershell
$env:CEREBRAS_API_KEY="your-key"
```

The actual key should never be committed to the repository.

### 4. Seed history

The 28 closed tickets are retained into the `bugtriage-seeded` bank:

```powershell
$env:HINDSIGHT_BANK="bugtriage-seeded"
python scripts\step2_seed.py
```

Seeding is resumable; successful tickets are recorded in the retention manifest.

### 5. Run the demo

```powershell
streamlit run app.py
```

The Streamlit UI opens on `http://localhost:8501`.

## Project structure

```text
bug-triage-agent/
├── agent/
│   ├── extract.py
│   ├── llm.py
│   ├── pipeline.py
│   ├── recall.py
│   ├── reason.py
│   └── retain_resolution.py
├── data/
│   └── bug_tickets_dataset.json
├── scripts/
│   ├── step2_seed.py
│   ├── step2_baseline.py
│   ├── step3_extract_test.py
│   ├── step4_reason_eval.py
│   ├── step5_eval_suite.py
│   └── step6_write_path_demo.py
├── app.py
├── requirements.txt
└── README.md
```

## Known limitations

- The final Step 5 regression run passed 6/8 cases rather than all 8.
- The two distractor tickets can be retrieved as their own historical memories; the current evaluator therefore records those self-matches as failures.
- Step 3 was an extraction validation step, not a separately scored retrieval benchmark.
- The measured average latency was 17.1 seconds per triage call in the Step 5 run, so the live demo should allow for LLM latency.
- The current UI's side-by-side cards use the local ticket lookup for the historical ticket details; Hindsight is responsible for recalling which historical memories are relevant.
- Hindsight's persistent memory is local to the configured Docker volume, so a fresh machine requires reseeding the history.