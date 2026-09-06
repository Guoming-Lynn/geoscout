from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(name: str, version: str = "v1") -> str:
    common = (PROMPTS_DIR / version / "common.txt").read_text(encoding="utf-8")
    body = (PROMPTS_DIR / version / f"{name}.txt").read_text(encoding="utf-8")
    parts = [common.strip(), body.strip()]
    if name in {"assess_dataset", "verify_dataset"}:
        schema = (PROMPTS_DIR / version / "json_assessment.txt").read_text(encoding="utf-8")
        parts.append(schema.strip())
    return "\n\n".join(parts)
