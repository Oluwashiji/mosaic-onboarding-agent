"""
What a "valid" onboarding plan looks like — used in two places:
- the Gemini function declaration (constrains generation)
- the pydantic model below (validates whatever comes back, independently)
"""

from typing import List
from pydantic import BaseModel, Field, field_validator


class Phase(BaseModel):
    phase_name: str
    start_day: int = Field(ge=1, le=90)
    end_day: int = Field(ge=1, le=90)
    goals: List[str] = Field(min_length=1)
    key_tasks: List[str] = Field(min_length=1)
    milestones: List[str] = Field(min_length=1)

    @field_validator("end_day")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("start_day")
        if start is not None and v < start:
            raise ValueError("end_day can't be before start_day")
        return v


class OnboardingPlan(BaseModel):
    role: str
    team: str
    company_context: str
    phases: List[Phase] = Field(min_length=1)
    success_metrics: List[str] = Field(min_length=1)


# Gemini's function-declaration format uses uppercase type names and isn't
# quite JSON Schema, so this is hand-written rather than derived from the
# pydantic model above.
_PHASE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "phase_name": {"type": "STRING", "description": "e.g. 'Days 1-30: Foundation'"},
        "start_day": {"type": "INTEGER"},
        "end_day": {"type": "INTEGER"},
        "goals": {"type": "ARRAY", "items": {"type": "STRING"}},
        "key_tasks": {"type": "ARRAY", "items": {"type": "STRING"}},
        "milestones": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["phase_name", "start_day", "end_day", "goals", "key_tasks", "milestones"],
}

ONBOARDING_PLAN_FUNCTION = {
    "name": "submit_onboarding_plan",
    "description": "Submit a structured 90-day onboarding plan for a new hire. Call this once, with the full plan.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "role": {"type": "STRING"},
            "team": {"type": "STRING"},
            "company_context": {"type": "STRING"},
            "phases": {"type": "ARRAY", "items": _PHASE_SCHEMA},
            "success_metrics": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["role", "team", "company_context", "phases", "success_metrics"],
    },
}
