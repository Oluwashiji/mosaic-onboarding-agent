from pydantic import ValidationError
from schema import OnboardingPlan
from agent import build_default_plan


def test_default_plan_is_valid():
    plan = build_default_plan("QA Engineer", "Quality", "Some context")
    OnboardingPlan.model_validate(plan)  # raises if invalid
    print("PASS: default fallback plan validates against schema")


def test_malformed_output_is_rejected():
    broken = {
        "role": "Backend Engineer",
        "team": "Platform",
        "company_context": "Mosaic Talent",
        "phases": [
            {
                "phase_name": "Days 1-30",
                "start_day": 30,   # invalid: start > end
                "end_day": 1,
                "goals": ["x"],
                "key_tasks": ["x"],
                "milestones": ["x"],
            }
        ],
        "success_metrics": ["x"],
    }
    try:
        OnboardingPlan.model_validate(broken)
        raise AssertionError("Expected ValidationError, got none")
    except ValidationError:
        print("PASS: malformed output (end_day < start_day) correctly rejected")


def test_missing_required_field_is_rejected():
    broken = {"role": "Backend Engineer", "team": "Platform"}  # missing everything else
    try:
        OnboardingPlan.model_validate(broken)
        raise AssertionError("Expected ValidationError, got none")
    except ValidationError:
        print("PASS: incomplete output correctly rejected")


if __name__ == "__main__":
    test_default_plan_is_valid()
    test_malformed_output_is_rejected()
    test_missing_required_field_is_rejected()
    print("\nAll checks passed.")
