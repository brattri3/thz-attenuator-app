"""
conftest.py - Pytest fixtures for multi-agent coordination dashboard test suite.
Provides isolated mock git repositories, canonical coordination files, CRLF line endings, and Unicode fixtures.
"""

from pathlib import Path
import subprocess
import sys
from typing import Dict
import pytest

# Ensure the dashboard package root and its parent are in sys.path
DASHBOARD_ROOT = Path(__file__).resolve().parent.parent
if str(DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT))
if str(DASHBOARD_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_ROOT.parent))

# This directory too, so a test module can `from conftest import shipped_hook`. pytest imports
# conftest by path without putting it on sys.path, and the alternative to one shared helper is
# the same path-resolution logic copied into three files -- which is the duplication this
# project spends most of its time removing.
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# ---------------------------------------------------------------------------------------
# This suite ships into consumer projects, and it runs in two different trees
# ---------------------------------------------------------------------------------------
#
# In the skill repository the files sit under `assets/`, where the hooks are staged as
# `dot-claude/hooks/` and the instruction files as `*.template`. The installer renames both
# on the way in, so an installed project has `.claude/hooks/` and filled-in files, and every
# path written for the staging layout resolves to nothing.
#
# That was issue #54: 41 of 334 tests failed on a clean installation, for a reason that had
# nothing to do with the project. A permanently red suite is worse than no suite -- it stops
# answering the question an update pass actually asks, which is "did I break something".
#
# Two different problems, so two different answers:
#
#   * The hook tests are worth keeping in a consumer project -- those hooks ARE installed and
#     do run there. They get a resolver, below.
#   * Tests of the skill repository's own layout (templates, `git ls-files assets/`, the
#     staging directory itself) cannot mean anything in a project that has none of it. They
#     are marked `skill_repo` and skipped where that layout is absent, the way `streamlit`
#     already marks the tests that need an optional dependency.

#: `assets/` in the skill repository; the project root in an installed project.
SCAFFOLD_ROOT = Path(__file__).resolve().parents[4]

#: True in the skill repository, where the pre-install staging layout exists.
IN_SKILL_REPO = (SCAFFOLD_ROOT / "dot-claude").is_dir()


def shipped_hook(name: str) -> Path:
    """Locate a hook in whichever of the two layouts this tree is.

    Installed layout wins when both exist, because a project that vendored the skill inside
    itself should still be testing the hook it actually runs.
    """
    installed = SCAFFOLD_ROOT / ".claude" / "hooks" / name
    if installed.exists():
        return installed
    return SCAFFOLD_ROOT / "dot-claude" / "hooks" / name


def pytest_configure(config):
    # Registered here rather than in pytest.ini, because pytest.ini lives at the skill repo
    # root and deliberately does NOT ship -- so in a consumer project every marked test
    # raised PytestUnknownMarkWarning. `streamlit` is registered for the same reason; it had
    # been warning in installed projects since it was introduced.
    config.addinivalue_line(
        "markers",
        "skill_repo: needs the skill repository's own pre-install layout (assets/, "
        "dot-claude/, *.template); skipped in an installed project",
    )
    config.addinivalue_line(
        "markers",
        "streamlit: requires streamlit to be installed (UI layer; skipped otherwise)",
    )


def pytest_collection_modifyitems(config, items):
    if IN_SKILL_REPO:
        return
    skip = pytest.mark.skip(
        reason="needs the skill repo's pre-install layout; this tree is an installed project")
    for item in items:
        if "skill_repo" in item.keywords:
            item.add_marker(skip)




CANONICAL_BOARD = """# Current Roles & Status

| Role | Status (date) | One-line summary |
|---|---|---|
| `lead` | active (2026-08-27) | Orchestrating multi-agent release |
| `worker_1` | active (2026-08-27) | Implementing parser and mutator |
| `worker_2` | idle (2026-08-26) | Awaiting test harness assignment |
| `auditor` | stale (2026-08-20) | Offline |
| `<ID>` | idle (YYYY-MM-DD) | Template role placeholder |
"""

CANONICAL_QUESTIONS = """# QUESTIONS & DECISIONS

## Batch 1: Architecture Decisions

| # | Question | Owner's answer | Type | Status |
|---|---|---|---|---|
| Q-1 | Should we support CRLF on Windows? | Yes, strict byte-level preservation | blocking | open |
| Q-2 | Is Streamlit rerun immediate? | Yes, via st.rerun() | non-blocking | resolved |
| Q-3 | Do we need git auto-commit isolation? | Yes, git commit --only | blocking | open |
| <ID> | Template question | — | non-blocking | open |

## Batch 2: Implementation Details

| # | Question | Owner's answer | Type | Status |
|---|---|---|---|---|
| Q-4 | How to handle `cat \\| grep` formulas? | Tokenized cell splitting | non-blocking | open |
"""

CANONICAL_HANDOFFS = """# Cross-Role Handoffs

## [2026-08-27] FROM lead TO worker_1 — Implement dashboard core
- What: Implement parser.py and mutator.py
- Context: User requested visual coordination tool
- Done when: Parsers and mutators handle all edge cases
- **Status:** taken

## [2026-08-27] FROM worker_1 TO worker_2 — Build comprehensive test suite
- What: Write pytest test suite for all modules
- Context: Quality verification
- Done when: 100% of test cases pass
- **Status:** open

## [2026-08-26] FROM lead TO auditor — Initial audit
- What: Verify codebase integrity
- Context: Compliance
- Done when: Report filed
- **Status:** done

## [TEMPLATE] FROM <ID> TO <ID> — Template handoff
- What: Placeholder
- Context: Placeholder
- Done when: Placeholder
- **Status:** open
"""

CANONICAL_INDEX = """# INDEX — open items in `QUESTIONS.md` and `HANDOFFS.md`
Built by coordination dashboard — summarizes number/status/line to jump to.

## QUESTIONS.md — open (3 of 4)
| # | Status | Role | Line | Summary |
|---|---|---|---|---|
| `Q-1` | open | | [line 8] | Should we support CRLF on Windows? |
| `Q-3` | open | | [line 10] | Do we need git auto-commit isolation? |
| `Q-4` | open | | [line 17] | How to handle `cat | grep` formulas? |

## HANDOFFS.md — open or missing status (2 of 4)
| # | Status | Line | Summary |
|---|---|---|---|
| `2026-08-27` | taken | [line 3] | Implement dashboard core |
| `2026-08-27` | open | [line 10] | Build comprehensive test suite |

<details><summary>QUESTIONS.md — closed (1)</summary>
| # | Status | Role | Line | Summary |
|---|---|---|---|---|
| `Q-2` | resolved | | [line 9] | Is Streamlit rerun immediate? |
</details>

<details><summary>HANDOFFS.md — closed (1)</summary>
| # | Status | Line | Summary |
|---|---|---|---|
| `2026-08-26` | done | [line 17] | Initial audit |
</details>
"""


def write_fixture(path: Path, text: str, newline: str = "\n") -> Path:
    """Write a fixture file with explicit line endings.

    Not Path.write_text(newline=...): that argument only exists on Python 3.10+, and the
    project's declared floor is 3.9. The 3.9 leg of CI is what caught this -- locally it
    passed on 3.11, which is exactly why the matrix is there.
    """
    with open(path, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)
    return path


@pytest.fixture
def mock_git_repo(tmp_path: Path) -> Dict[str, Path]:
    """
    Creates an isolated git repository with canonical coordination files committed to git.
    Configures git user.name and user.email for deterministic commit operations.
    """
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Initialize git repo
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test Coordinator"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "coordinator@test.local"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo_dir, check=True, capture_output=True)

    # Create assets/coordination directory
    coord_dir = repo_dir / "assets" / "coordination"
    coord_dir.mkdir(parents=True, exist_ok=True)

    board_file = coord_dir / "BOARD.md"
    write_fixture(board_file, CANONICAL_BOARD, "\n")

    questions_file = coord_dir / "QUESTIONS.md"
    write_fixture(questions_file, CANONICAL_QUESTIONS, "\n")

    handoffs_file = coord_dir / "HANDOFFS.md"
    write_fixture(handoffs_file, CANONICAL_HANDOFFS, "\n")

    index_file = coord_dir / "INDEX.md"
    write_fixture(index_file, CANONICAL_INDEX, "\n")

    # Initial commit of coordination files
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: initialize coordination journals", "--trailer", "Role: lead"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True
    )

    return {
        "repo_dir": repo_dir,
        "coord_dir": coord_dir,
        "board_file": board_file,
        "questions_file": questions_file,
        "handoffs_file": handoffs_file,
        "index_file": index_file
    }


@pytest.fixture
def russian_content_files(tmp_path: Path) -> Dict[str, Path]:
    """Canonical ENGLISH headers and status keywords, with Russian prose and emoji as content.

    This is the supported shape for a non-English project, and it must keep working: the
    status/type keywords and table headers are protocol tokens that tooling parses, while
    questions, answers, summaries and handoff bodies are prose in the project's own language.

    Contrast with `russian_schema_files`, where the protocol tokens themselves are Russian
    and the tools must refuse to guess.
    """
    coord = tmp_path / "ru_content"
    coord.mkdir(parents=True, exist_ok=True)

    board = (
        "# Статус ролей 🤖\n\n"
        "| Role | Status (date) | One-line summary |\n"
        "|---|---|---|\n"
        "| архитектор | active (2026-08-27) | Разработка архитектуры и контрактов 📐 |\n"
        "| тестировщик | idle (2026-08-26) | Ожидание сборки тест-раннера 🧪 |\n"
    )
    questions = (
        "# Вопросы и решения ❓\n\n"
        "## Пакет 1\n\n"
        "| # | Question | Owner's answer | Type | Status |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Поддерживаем ли UTF-8 и эмодзи 🚀? | Да, полная поддержка | blocking | open |\n"
        "| Q-2 | Формула $\\int_0^1 x^2 dx$ верна? | Абсолютно точно | non-blocking | resolved |\n"
        "| Q-3 | Как экранировать `cat \\| grep`? | Символом `\\|` | blocking | open |\n"
    )
    handoffs = (
        "# Передачи задач 🤝\n\n"
        "## [2026-08-27] FROM архитектор TO тестировщик — Создание модуля парсера\n"
        "- What: Написать `parser.py` с поддержкой русского языка\n"
        "- Context: Проект координации мультиагентов\n"
        "- Done when: Все тесты проходят успешно 🎉\n"
        "- **Status:** taken\n"
    )

    files = {"dir": coord}
    for name, text in (("BOARD", board), ("QUESTIONS", questions), ("HANDOFFS", handoffs)):
        path = coord / f"{name}.md"
        write_fixture(path, text, "\n")
        files[f"{name.lower()}_file"] = path
    return files


@pytest.fixture
def russian_schema_files(tmp_path: Path) -> Dict[str, Path]:
    """Russian PROTOCOL tokens: translated headers and translated status/type values.

    This is the shape the tools must reject with an explicit diagnostic rather than parse
    into believable-looking numbers. The skill's references/rationale.md records what happened when the
    source project let `Статус:` drift in alongside `Status:`.
    """
    coord = tmp_path / "ru_schema"
    coord.mkdir(parents=True, exist_ok=True)

    board = (
        "# Статус ролей\n\n"
        "| Роль | Статус (дата) | Описание |\n"
        "|---|---|---|\n"
        "| архитектор | активен (2026-08-27) | Разработка архитектуры |\n"
        "| тестировщик | в_процессе (2026-08-26) | Написание тестов |\n"
    )
    questions = (
        "# Вопросы\n\n"
        "| № | Вопрос | Ответ | Тип | Статус |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Первый вопрос? | — | блокирующий | открыт |\n"
        "| Q-2 | Второй вопрос? | Да | неблокирующий | решён |\n"
    )
    handoffs = (
        "# Передачи\n\n"
        "## [2026-08-27] FROM архитектор TO тестировщик — Модуль парсера\n"
        "- What: Написать парсер\n"
        "- **Status:** открыт\n"
    )

    files = {"dir": coord}
    for name, text in (("BOARD", board), ("QUESTIONS", questions), ("HANDOFFS", handoffs)):
        path = coord / f"{name}.md"
        write_fixture(path, text, "\n")
        files[f"{name.lower()}_file"] = path
    return files


@pytest.fixture
def unicode_markdown_files(tmp_path: Path) -> Dict[str, Path]:
    """
    Creates coordination markdown files containing Cyrillic headers, emojis, and multibyte math symbols.
    """
    unicode_dir = tmp_path / "unicode_coord"
    unicode_dir.mkdir(parents=True, exist_ok=True)

    board_content = (
        "# Статус Ролей и Команды 🤖\n\n"
        "| Роль | Статус (дата) | Описание |\n"
        "|---|---|---|\n"
        "| `архитектор` | active (2026-08-27) | Разработка архитектуры и контрактов 📐 |\n"
        "| `разработчик` | active (2026-08-27) | Реализация парсеров и мутаторов 🚀 |\n"
        "| `тестировщик` | idle (2026-08-26) | Ожидание сборки тест-раннера 🧪 |\n"
    )

    questions_content = (
        "# Вопросы и Решения ❓\n\n"
        "## Пакет 1: Русскоязычные вопросы\n\n"
        "| № | Вопрос | Ответ | Тип | Статус |\n"
        "|---|---|---|---|---|\n"
        "| Q-1 | Поддерживаем ли UTF-8 и эмодзи 🚀? | Да, полная поддержка UTF-8 | blocking | open |\n"
        "| Q-2 | Формула $\\int_0^1 x^2 dx = \\frac{1}{3}$ корректна? | Абсолютно точно | non-blocking | resolved |\n"
        "| Q-3 | Как экранировать `cat \\| grep` в таблице? | Символом `\\|` | blocking | open |\n"
    )

    handoffs_content = (
        "# Передачи Задач 🤝\n\n"
        "## [2026-08-27] FROM архитектор TO разработчик — Создание модуля парсера\n"
        "- What: Написать `parser.py` с поддержкой русского языка\n"
        "- Context: Проект координации мультиагентов\n"
        "- Done when: Все тесты проходят успешно 🎉\n"
        "- **Status:** taken\n\n"
        "## [2026-08-27] FROM разработчик TO тестировщик — Написание тестов\n"
        "- What: Покрыть все крайние случаи тестами\n"
        "- Context: Верификация функционала\n"
        "- Done when: 100% тестов зеленые\n"
        "- **Status:** open\n"
    )

    board_file = unicode_dir / "BOARD.md"
    write_fixture(board_file, board_content, "\n")

    questions_file = unicode_dir / "QUESTIONS.md"
    write_fixture(questions_file, questions_content, "\n")

    handoffs_file = unicode_dir / "HANDOFFS.md"
    write_fixture(handoffs_file, handoffs_content, "\n")

    return {
        "dir": unicode_dir,
        "board_file": board_file,
        "questions_file": questions_file,
        "handoffs_file": handoffs_file
    }
