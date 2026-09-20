#!/usr/bin/env python3
"""
Generates a personalized 90-day onboarding plan for a new hire.

Flow: forced function call to Gemini -> validate the result independently
against the pydantic schema -> retry (with the error fed back) if it's
invalid -> fall back to a deterministic template plan if it still isn't
working after a couple of tries.

Details on why it's built this way are in README.md.
"""

import argparse
import json
import os
import sys
import time

from pydantic import ValidationError
from dotenv import load_dotenv

from schema import OnboardingPlan, ONBOARDING_PLAN_FUNCTION

load_dotenv()

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_RETRIES_DEFAULT = 2


def log(msg):
    print(f"[agent] {msg}", file=sys.stderr)


SYSTEM_PROMPT = (
    "You are an onboarding design assistant for Mosaic Talent, a platform that "
    "helps new hires succeed in their first 90 days. Given a new hire's role, "
    "team, and company context, call submit_onboarding_plan exactly once with "
    "a complete, realistic 90-day plan.\n\n"
    "Structure it as 3 phases (roughly days 1-30, 31-60, 61-90). Goals, tasks "
    "and milestones should be specific to the stated role and team, not "
    "generic onboarding filler."
)


def build_prompt(role, team, company_context):
    return (
        f"New hire role: {role}\n"
        f"Team: {team}\n"
        f"Company context: {company_context}\n\n"
        "Generate the 90-day onboarding plan now via the tool."
    )


def call_model(role, team, company_context, model, prior_error=None):
    """One API call. Returns the raw dict from the function call args.
    Raises on any API-level failure (auth, network, rate limit, etc)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    prompt = build_prompt(role, team, company_context)
    if prior_error:
        # feed the model its own mistake instead of just asking again
        prompt += (
            "\n\nYour last attempt didn't match the required schema:\n"
            f"{prior_error}\n\nCall submit_onboarding_plan again and fix it."
        )

    tool = types.Tool(function_declarations=[ONBOARDING_PLAN_FUNCTION])

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[tool],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
        ),
    )

    candidate = response.candidates[0] if response.candidates else None
    if not candidate or not candidate.content.parts:
        raise ValueError("Empty response from the model.")

    for part in candidate.content.parts:
        fc = getattr(part, "function_call", None)
        if fc and fc.name == "submit_onboarding_plan":
            return dict(fc.args)

    raise ValueError("Model responded without calling submit_onboarding_plan.")


def build_default_plan(role, team, company_context):
    """No LLM here on purpose - this is the last rung of the fallback
    ladder, so it needs to work even if the API is completely down."""
    return {
        "role": role,
        "team": team,
        "company_context": company_context,
        "phases": [
            {
                "phase_name": "Days 1-30: Foundation",
                "start_day": 1,
                "end_day": 30,
                "goals": [
                    f"Understand the {team} team's goals and how {role} supports them",
                    "Get environment, tools, and access fully set up",
                    "Build relationships with immediate teammates and stakeholders",
                ],
                "key_tasks": [
                    "Complete company and team onboarding materials",
                    "Shadow at least one teammate's typical workflow",
                    "Set up 1:1s with manager and key collaborators",
                ],
                "milestones": [
                    "Fully set up and able to work independently on small tasks",
                    "Completed first small, low-risk deliverable",
                ],
            },
            {
                "phase_name": "Days 31-60: Contribution",
                "start_day": 31,
                "end_day": 60,
                "goals": [
                    f"Take ownership of a real {role} workstream",
                    "Understand team processes, cadences, and quality bar",
                ],
                "key_tasks": [
                    "Own an end-to-end task or small project with guidance",
                    "Start participating actively in team rituals (standups, reviews, planning)",
                ],
                "milestones": [
                    "Delivered first independent piece of meaningful work",
                    "Received and incorporated first round of substantive feedback",
                ],
            },
            {
                "phase_name": "Days 61-90: Ownership",
                "start_day": 61,
                "end_day": 90,
                "goals": [
                    "Operate with increasing independence",
                    "Identify one improvement to propose to the team",
                ],
                "key_tasks": [
                    "Lead or co-lead a project or initiative",
                    "Present learnings or a proposal to the team",
                ],
                "milestones": [
                    "Operating as a fully contributing team member",
                    "Clear plan in place for the next 90 days",
                ],
            },
        ],
        "success_metrics": [
            "New hire is producing independent, reviewed work by day 90",
            "New hire reports feeling clear on expectations and team fit",
            "Manager confirms onboarding goals were met",
        ],
    }


def generate_plan(role, team, company_context, model, max_retries, dry_run):
    """Runs the full pipeline. Returns (plan_dict, path_taken)."""
    if dry_run:
        log("--dry-run set, skipping the API call and using the default template.")
        plan = build_default_plan(role, team, company_context)
        OnboardingPlan.model_validate(plan)
        return plan, "fallback_default (dry-run)"

    last_error = None
    for attempt in range(1, max_retries + 2):
        try:
            log(f"calling Gemini (attempt {attempt}/{max_retries + 1})...")
            raw = call_model(role, team, company_context, model, prior_error=last_error)
        except Exception as err:
            last_error = str(err)
            log(f"API call failed: {last_error}")
            if attempt <= max_retries:
                backoff = 2 ** (attempt - 1)
                log(f"retrying in {backoff}s...")
                time.sleep(backoff)
                continue
            break

        try:
            validated = OnboardingPlan.model_validate(raw)
            path = "llm_first_try" if attempt == 1 else "llm_after_retry"
            return validated.model_dump(), path
        except ValidationError as ve:
            last_error = str(ve)
            log(f"schema validation failed: {last_error}")
            if attempt <= max_retries:
                continue
            break

    log("Out of retries — falling back to the default template plan.")
    plan = build_default_plan(role, team, company_context)
    OnboardingPlan.model_validate(plan)
    return plan, "fallback_default"


def print_summary(plan, path):
    print(f"\n=== Onboarding plan ({path}) ===\n")
    print(f"Role: {plan['role']}  |  Team: {plan['team']}")
    print(f"Context: {plan['company_context']}\n")
    for phase in plan["phases"]:
        print(f"-- {phase['phase_name']} (days {phase['start_day']}-{phase['end_day']}) --")
        print("  Goals:")
        for g in phase["goals"]:
            print(f"    - {g}")
        print("  Key tasks:")
        for t in phase["key_tasks"]:
            print(f"    - {t}")
        print("  Milestones:")
        for m in phase["milestones"]:
            print(f"    - {m}")
        print()
    print("Success metrics:")
    for s in plan["success_metrics"]:
        print(f"  - {s}")


def main():
    parser = argparse.ArgumentParser(description="Generate a 90-day onboarding plan.")
    parser.add_argument("--role", default="Backend Engineer")
    parser.add_argument("--team", default="Platform Engineering")
    parser.add_argument(
        "--context",
        default=(
            "Mosaic Talent is a B2B SaaS talent-development platform for growing "
            "SMBs, focused on making a new hire's first 90 days effective through "
            "AI-driven automation."
        ),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES_DEFAULT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the API call and use the fallback plan (no key needed).",
    )
    parser.add_argument("--out", default="onboarding_plan.json")
    args = parser.parse_args()

    plan, path = generate_plan(
        role=args.role,
        team=args.team,
        company_context=args.context,
        model=args.model,
        max_retries=args.max_retries,
        dry_run=args.dry_run,
    )

    with open(args.out, "w") as f:
        json.dump(plan, f, indent=2)
    log(f"saved to {args.out}")

    print_summary(plan, path)


if __name__ == "__main__":
    main()
