# Onboarding Plan Agent

A small AI agent that turns a new hire's role, team, and company context into
a personalized, structured 90-day onboarding plan — built for the Mosaic
Talent technical assessment.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env   # then add your GEMINI_API_KEY

# Run with the built-in sample input
python3 agent.py

# Or supply your own
python3 agent.py --role "Sales Development Rep" --team "Revenue" \
  --context "Series A fintech startup, remote-first, fast-paced"

# Run the pipeline without any API key (exercises the fallback path only)
python3 agent.py --dry-run

# Sanity-check the schema/fallback logic directly
python3 test_fallback.py
```

Uses Gemini (`gemini-2.5-flash` by default, configurable via `GEMINI_MODEL`
in `.env`) — a free key is available at aistudio.google.com/apikey. The
architecture underneath isn't tied to any one provider; swapping in Claude
or OpenAI would mean changing `call_model()` and the function schema in
`schema.py`, not the retry/validation/fallback logic around them.

Output is written to `onboarding_plan.json` and also printed as a readable
summary to stdout.

## Approach to structuring the agent's output

The core design decision was: **don't let the model return prose and hope
to parse it.** Instead:

1. **`schema.py`** defines the plan shape twice, deliberately:
   - as a hand-written function declaration (`ONBOARDING_PLAN_FUNCTION`)
     that's handed to Gemini with `tool_config` forced to `mode="ANY"`, so
     the model has to call it — it can't just reply with prose.
   - as a `pydantic` model (`OnboardingPlan`) that independently re-validates
     whatever the model actually returns.

   These are kept separate on purpose. A model can call a tool and satisfy
   its JSON Schema (right types, required keys present) while still being
   semantically wrong — e.g. `end_day < start_day`, or empty task lists.
   The JSON Schema catches *shape*; pydantic's validators catch *meaning*.
   I don't treat "the model used the tool" as "the output is trustworthy."

2. The plan is a fixed structure — three `Phase` objects (day ranges,
   goals, key tasks, milestones) plus top-level `success_metrics` — because
   that maps directly to what the product needs to render, not just what an
   LLM finds easy to produce.

## How the fallback/error handling works

There's a three-rung ladder, and every rung is logged (`[agent] ...` lines
to stderr) so it's obvious after the fact which path a given run took:

1. **Schema validation failure** → the agent retries, but not blindly: the
   pydantic `ValidationError` text is fed back into the next request as a
   user message ("your previous call didn't match the schema because X, fix
   it"), so the retry is informed rather than a repeat of the same mistake.
2. **API-level failure** (auth, network, rate limit, or the model simply not
   calling the tool at all) → retried with exponential backoff, separately
   from schema-validation retries, since these need different handling
   (there's no "error to feed back" for a network timeout).
3. **All retries exhausted** → `build_default_plan()` produces a
   deterministic, generic-but-usable 3-phase plan from the same role/team/
   context inputs, with no LLM involved. It's validated against the exact
   same pydantic schema before being returned, so downstream code never has
   to know or care whether a given plan came from the model or the fallback.

The `--max-retries` flag controls steps 1–2 (default: 2 retries, so 3 total
attempts before falling back). `--dry-run` skips the API entirely and goes
straight to the fallback plan — useful for testing the pipeline and schema
without burning API calls or needing a key.

`test_fallback.py` exercises the schema/fallback logic in isolation
(malformed day ranges, missing fields, and the fallback plan itself) without
touching the network, so the failure-handling logic can be verified in CI
without an API key.

## What I'd improve with more time

- **Structured logging instead of print statements** — emit each attempt
  (success/failure, latency, which rung of the fallback ladder) as JSON
  events, so this could feed a dashboard on retry/fallback rates in
  production — that rate is itself a useful reliability signal.
- **Partial-credit validation** — right now a validation failure discards
  the whole response and retries from scratch. A more advanced version
  would keep the parts of the plan that did validate (e.g. phase 1 was
  fine, phase 2 had a bad day range) and only ask the model to fix the
  broken part.
- **Input validation/sanitization** — role/team/context are currently
  passed straight into the prompt. For a real product surface this needs
  basic guarding against prompt injection via user-supplied fields.
- **Caching** — identical (role, team, context) triples shouldn't need a
  fresh generation every time.
- **Configurable phase count** — hardcoded to 3 phases (30/60/90). A
  90-day plan for a very senior or very junior hire might reasonably want
  a different cadence.
- **Async/concurrent generation** for batch use (e.g. generating plans for
  a whole cohort of new hires at once).
- **Real integration tests against the live API** (currently only the
  fallback/validation logic is tested without a key; the happy path against
  the actual model isn't covered by `test_fallback.py`).

## Files

- `agent.py` — CLI entry point, model call, retry/fallback orchestration.
- `schema.py` — JSON Schema (tool definition) + pydantic validation model.
- `test_fallback.py` — schema/fallback sanity checks, no API key required.
- `requirements.txt` — dependencies.
