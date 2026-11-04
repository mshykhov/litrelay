from __future__ import annotations

import csv
import io
import json
import re
import shutil
from pathlib import Path

from litrelay.book_inputs import validate_chapter
from litrelay.glossary_versioning import apply_glossary_overrides, validate_glossary
from litrelay.project_storage import digest, project_lock, write_json
from litrelay.project_workflow import _inputs, export_project, project_status
from litrelay.term_fix_plan import review_fingerprint, validate_replacement


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def apply_term_fix(project: Path, plan_path: Path) -> dict:
    project, plan_path = project.resolve(), plan_path.resolve()
    if plan_path.parent.parent != project / "work/term-fixes" or plan_path.suffix != ".json":
        raise ValueError("Plan must belong to work/term-fixes/<attempt>/<plan>.json")
    with project_lock(project):
        return _apply(project, plan_path)


def _apply(project: Path, plan_path: Path) -> dict:
    operation = plan_path.parent
    applied = operation / "applied.json"
    status = project_status(project)
    if applied.exists():
        result = json.loads(applied.read_text(encoding="utf-8"))
        if status["fingerprint"] != result["after_fingerprint"] or status["chapters"] != result["accepted_after"]:
            raise ValueError("Project changed after this term fix; create a new plan")
        return {**result, "already_applied": True}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    config, source, _, fingerprint = _inputs(project)
    if plan.get("version") != 1 or plan.get("project_fingerprint") != fingerprint:
        raise ValueError("Stale or unsupported term-fix plan")
    if not status["bootstrap_ready"] or not status["chapters"]:
        raise ValueError("Project needs current accepted chapters")
    hashes = plan.get("chapter_sha256", {})
    if set(hashes) != set(status["chapters"]) or any(
        status["chapters"][n]["target_sha256"] != value for n, value in hashes.items()
    ):
        raise ValueError("Accepted chapters changed since planning")
    term, target = plan.get("source_term", ""), plan.get("target", "")
    if not isinstance(term, str) or not term.strip() or not isinstance(target, str) or not target.strip():
        raise ValueError("Source term and target must be nonempty strings")
    if not any(term in text for text in source.values()):
        raise ValueError("Source term is absent from the original")
    validate_replacement(target, config["target_language"])
    pattern = re.compile(plan["pattern"])
    span_mode = plan.get("span_mode", "word")
    span_limit = plan.get("span_limit", 120)
    if span_mode not in {"word", "context"} or span_limit != {"word": 120, "context": 1200}[span_mode]:
        raise ValueError("Unsupported edit-span limits")
    if pattern.search("") is not None:
        raise ValueError("Empty matches are forbidden")
    originals = {n: (project / f"work/accepted/{int(n):04d}.txt").read_text(encoding="utf-8") for n in hashes}
    expected = {
        (int(n), m.start(), m.end(), m.group()) for n, text in originals.items() for m in pattern.finditer(text)
    }
    patches = plan.get("patches", [])
    actual = set()
    ids = set()
    for patch in patches:
        if not isinstance(patch, dict) or not isinstance(patch.get("old"), str):
            raise ValueError("Invalid patch structure")
        if patch.get("uncertain") is not False:
            raise ValueError("Plan contains uncertain replacements; review it before applying")
        if patch.get("id") in ids or not isinstance(patch.get("id"), str):
            raise ValueError("Duplicate or invalid patch ID")
        ids.add(patch["id"])
        if any(type(patch.get(key)) is not int for key in ["chapter", "start", "end"]):
            raise ValueError("Patch offsets must be integers")
        key = (patch["chapter"], patch["start"], patch["end"], patch["old"])
        if key not in expected or key in actual or patch["end"] <= patch["start"]:
            raise ValueError("Patch does not match an original occurrence")
        actual.add(key)
        replacement = patch.get("replacement")
        validate_replacement(replacement, config["target_language"], span_mode=span_mode, span_limit=span_limit)
        if len(patch["old"]) > span_limit:
            raise ValueError("Original edit span is too long")
        if span_mode == "context" and re.findall(r"\d+(?:[.,]\d+)?", patch["old"]) != re.findall(
            r"\d+(?:[.,]\d+)?", replacement
        ):
            raise ValueError("Context edit changed numerical facts")
    if actual != expected:
        raise ValueError("Plan does not cover every matched occurrence")
    if plan.get("reviewed") is not True or plan.get("review_sha256") != review_fingerprint(plan):
        raise ValueError("Plan needs AI review, or was edited after review")
    changed = {}
    for n, text in originals.items():
        edits = sorted((p for p in patches if p["chapter"] == int(n)), key=lambda p: p["start"], reverse=True)
        updated = text
        for patch in edits:
            updated = updated[: patch["start"]] + patch["replacement"] + updated[patch["end"] :]
        if pattern.search(updated):
            raise ValueError(f"Old term remains in chapter {n}")
        if span_mode == "context" and re.search(plan["match_pattern"], updated):
            raise ValueError(f"Old term remains in context-edited chapter {n}")
        validate_chapter(int(n), updated, min_chars=config["min_chars"], target_language=config["target_language"])
        if updated != text:
            changed[n] = updated
    overrides = project / "input/term-overrides.csv"
    glossary = project / "work/glossary/active.csv"
    with glossary.open(encoding="utf-8") as handle:
        canonical = {row["source"]: row for row in csv.DictReader(handle)}
    fields = ["source", "target_ru", "type", "note", "confidence"]
    rows = list(csv.DictReader(io.StringIO(overrides.read_text(encoding="utf-8")))) if overrides.exists() else []
    if (
        not patches
        and any(row.get("source") == term and row.get("target_ru") == target for row in rows)
        and canonical.get(term, {}).get("target_ru") == target
    ):
        result = {
            "after_fingerprint": fingerprint,
            "accepted_after": status["chapters"],
            "changed_chapters": [],
            "replacements": 0,
            "source_term": term,
            "target": target,
            "backup": None,
            "complete": status["complete"],
            "outputs": {},
            "already_canonical": True,
        }
        write_json(applied, result)
        return result
    rows = [{key: row.get(key, "") for key in fields} for row in rows if row.get("source") != term]
    rows.append(
        {
            "source": term,
            "target_ru": target,
            "type": canonical.get(term, {}).get("type") or "term",
            "note": canonical.get(term, {}).get("note") or "Reader-approved canonical term",
            "confidence": "1.0",
        }
    )
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    staged_override = operation / "term-overrides.csv"
    staged_override.write_text(stream.getvalue(), encoding="utf-8")
    staged_glossary = operation / "glossary.updated.csv"
    apply_glossary_overrides(glossary, staged_override, staged_glossary)
    if not validate_glossary(staged_glossary).ok:
        raise ValueError("Updated glossary is invalid")
    progress = project / "work/progress.json"
    state = json.loads(progress.read_text(encoding="utf-8"))
    touched = [glossary, overrides, progress, *[project / f"work/accepted/{int(n):04d}.txt" for n in changed]]
    touched += [project / "output" / name for name in ["book.txt", "book.epub", "book.zip", "report.json"]]
    backup = operation / "backup"
    if (operation / "transaction.json").exists():
        transaction = json.loads((operation / "transaction.json").read_text(encoding="utf-8"))
        if transaction.get("status") == "applying":
            raise ValueError(f"Incomplete transaction; inspect {operation / 'backup.json'} before retrying")
    manifest = []
    for path in touched:
        relative = path.relative_to(project)
        existed = path.exists()
        manifest.append({"path": str(relative), "existed": existed})
        if existed:
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    write_json(operation / "backup.json", {"files": manifest})
    write_json(operation / "transaction.json", {"status": "applying", "plan": str(plan_path.relative_to(project))})
    try:
        _write_text(overrides, stream.getvalue())
        _write_text(glossary, staged_glossary.read_text(encoding="utf-8"))
        after_fingerprint = _inputs(project, allow_pending_term_fix=True)[3]
        for n, row in state["chapters"].items():
            if n not in status["chapters"]:
                continue
            row["fingerprint"] = after_fingerprint
            if n in changed:
                previous_hash = row["target_sha256"]
                _write_text(project / f"work/accepted/{int(n):04d}.txt", changed[n])
                row["target_sha256"] = digest(changed[n])
                row.setdefault("editorial_changes", []).append(
                    {
                        "kind": "term_fix",
                        "plan": str(plan_path.relative_to(project)),
                        "previous_target_sha256": previous_hash,
                        "target_sha256": row["target_sha256"],
                    }
                )
                row.setdefault("qa_target_sha256", previous_hash)
        state["fingerprint"] = state["glossary_fingerprint"] = after_fingerprint
        write_json(progress, state)
        after = project_status(project, allow_pending_term_fix=True)
        if set(after["chapters"]) != set(status["chapters"]):
            raise RuntimeError("Term fix invalidated accepted chapters")
        result = export_project(project, allow_pending_term_fix=True) if after["complete"] else after
        summary = {
            "after_fingerprint": after_fingerprint,
            "accepted_after": after["chapters"],
            "changed_chapters": sorted(map(int, changed)),
            "replacements": len(patches),
            "source_term": term,
            "target": target,
            "backup": str(backup),
            "complete": result["complete"],
            "outputs": result.get("outputs", {}),
        }
        write_json(applied, summary)
        write_json(operation / "transaction.json", {"status": "applied"})
        return summary
    except BaseException:
        for entry in reversed(manifest):
            path = project / entry["path"]
            if entry["existed"]:
                shutil.copy2(backup / entry["path"], path)
            else:
                path.unlink(missing_ok=True)
        applied.unlink(missing_ok=True)
        write_json(operation / "transaction.json", {"status": "rolled_back"})
        raise
