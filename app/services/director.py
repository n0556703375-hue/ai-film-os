from app.services.prompt_builder import build_prompt
from app.services.continuity import check_shot_continuity

def run_director(shot: dict) -> dict:
    issues = check_shot_continuity(shot)
    blocking = [i for i in issues if i["severity"] == "high"]
    return {
        "ready": not blocking,
        "issues": issues,
        "prompt": build_prompt(shot) if not blocking else None,
        "next_action": "generate_reference" if not blocking else "fix_blocking_issues",
    }
