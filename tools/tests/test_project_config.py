import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def requirement_lines(path: Path) -> set[str]:
    return {
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith(("#", "-r "))
    }


def test_requirements_files_match_pyproject_dependency_groups() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)

    assert requirement_lines(ROOT / "server" / "requirements.txt") == set(
        project["project"]["dependencies"]
    )
    assert requirement_lines(ROOT / "server" / "requirements-dev.txt") == set(
        project["project"]["optional-dependencies"]["dev"]
    )
