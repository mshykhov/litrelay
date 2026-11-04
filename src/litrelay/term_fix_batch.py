from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from litrelay.project_workflow import Requester, _inputs
from litrelay.term_fix_apply import apply_term_fix
from litrelay.term_fix_plan import propose_term_fix, validate_replacement


class TermFixBatchError(RuntimeError):
    def __init__(self, source_term: str, completed: list[str], plans: list[dict], cause: Exception) -> None:
        self.source_term = source_term
        self.completed_source_terms = list(completed)
        self.plans = list(plans)
        super().__init__(f"Term {source_term!r} failed: {cause}. Completed source terms: {completed}")


def fix_terms(
    project: Path,
    rules: list[dict],
    *,
    apply: bool = False,
    requester: Requester | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    review_model: str | None = None,
    review_reasoning_effort: str | None = None,
    event_handler: Callable[[dict], None] | None = None,
) -> dict:
    config, source, _, _ = _inputs(project)
    if not isinstance(rules, list) or not rules:
        raise ValueError("Rules must be a nonempty list")
    seen = set()
    validated = []
    for index, rule in enumerate(rules, 1):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule {index} must be an object")
        term, target, pattern = (rule.get(key) for key in ("source_term", "target", "pattern"))
        if any(not isinstance(value, str) or not value.strip() for value in (term, target, pattern)):
            raise ValueError(f"Rule {index} needs nonempty source_term, target and pattern")
        if term in seen:
            raise ValueError(f"Duplicate source term: {term}")
        seen.add(term)
        if not any(term in text for text in source.values()):
            raise ValueError(f"Source term is absent from the original: {term}")
        validate_replacement(target, config["target_language"])
        try:
            re.compile(pattern)
            minimum_width = re._parser.parse(pattern, 0).getwidth()[0]
        except (re.error, OverflowError) as error:
            raise ValueError(f"Invalid pattern in rule {index}: {error}") from error
        if minimum_width == 0:
            raise ValueError(f"Pattern in rule {index} can match empty text")
        validated.append((term, target, pattern))
    valid_efforts = {None, "low", "medium", "high", "xhigh", "max"}
    if reasoning_effort not in valid_efforts or review_reasoning_effort not in valid_efforts:
        raise ValueError("Invalid reasoning effort")
    completed = []
    plans = []
    for term, target, pattern in validated:
        try:
            if event_handler:
                event_handler({"event": "term_fix_started", "source_term": term, "target": target})
            plan = propose_term_fix(
                project,
                term,
                target,
                pattern,
                requester=requester,
                model=model,
                reasoning_effort=reasoning_effort,
                review_model=review_model,
                review_reasoning_effort=review_reasoning_effort,
            )
            metadata = {
                "source_term": term,
                "target": target,
                "plan_path": plan["plan_path"],
                "matches": len(plan["patches"]),
                "uncertain": sum(p["uncertain"] for p in plan["patches"]),
                "reviewed": plan.get("reviewed", False),
                "usage": plan.get("usage", []),
                "review_usage": plan.get("review_usage", []),
            }
            plans.append(metadata)
            if event_handler:
                event_handler(
                    {
                        "event": "term_fix_reviewed",
                        "source_term": term,
                        "matches": metadata["matches"],
                        "uncertain": metadata["uncertain"],
                    }
                )
            if apply:
                result = apply_term_fix(project, Path(plan["plan_path"]))
                metadata["applied"] = True
                metadata["changed_chapters"] = result.get("changed_chapters", [])
                metadata["after_fingerprint"] = result.get("after_fingerprint")
                if event_handler:
                    event_handler(
                        {
                            "event": "term_fix_applied",
                            "source_term": term,
                            "changed_chapters": result.get("changed_chapters", []),
                            "replacements": result.get("replacements", 0),
                        }
                    )
            completed.append(term)
        except Exception as error:
            raise TermFixBatchError(term, completed, plans, error) from error
    return {"applied": apply, "completed_source_terms": completed, "plans": plans}
