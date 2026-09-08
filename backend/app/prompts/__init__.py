from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent
REVIEWER_PROMPTS = {"assess_dataset", "verify_dataset"}


def load_prompt(name: str, version: str = "v1") -> str:
    root = PROMPTS_DIR / version
    parts = [(root / "common.txt").read_text(encoding="utf-8").strip()]
    if name in REVIEWER_PROMPTS:
        parts.append((root / "reviewer.txt").read_text(encoding="utf-8").strip())
    parts.append((root / f"{name}.txt").read_text(encoding="utf-8").strip())
    if name in REVIEWER_PROMPTS:
        parts.append((root / "json_assessment.txt").read_text(encoding="utf-8").strip())
    return "\n\n".join(parts)
