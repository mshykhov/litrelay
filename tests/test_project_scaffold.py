import json
from pathlib import Path

from litrelay.project_scaffold import create_novel_project


def test_create_novel_project_scaffolds_public_and_private_files(tmp_path: Path) -> None:
    summary = create_novel_project(
        tmp_path,
        slug="test-novel",
        title="Test Novel",
        source_lang="Chinese",
        target_lang="Russian",
    )

    assert summary.created_files == 3
    assert (tmp_path / "examples/test-novel/README.md").exists()
    assert (tmp_path / "examples/test-novel/source-acquisition.md").exists()
    project_json = tmp_path / "private/projects/test-novel/project.json"
    assert project_json.exists()

    project = json.loads(project_json.read_text(encoding="utf-8"))
    assert project["slug"] == "test-novel"
    assert project["title"] == "Test Novel"
    assert project["source_lang"] == "Chinese"
    assert project["target_lang"] == "Russian"

    expected_dirs = [
        "private/projects/test-novel/raw/source",
        "private/projects/test-novel/raw/ru",
        "private/projects/test-novel/metadata",
        "private/projects/test-novel/working/glossary",
        "private/projects/test-novel/working/batches",
        "private/projects/test-novel/working/qa",
        "private/projects/test-novel/working/accepted",
    ]
    for directory in expected_dirs:
        assert (tmp_path / directory).is_dir()
