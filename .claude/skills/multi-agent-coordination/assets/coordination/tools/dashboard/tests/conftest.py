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
    board_file.write_text(CANONICAL_BOARD, encoding="utf-8", newline="\n")

    questions_file = coord_dir / "QUESTIONS.md"
    questions_file.write_text(CANONICAL_QUESTIONS, encoding="utf-8", newline="\n")

    handoffs_file = coord_dir / "HANDOFFS.md"
    handoffs_file.write_text(CANONICAL_HANDOFFS, encoding="utf-8", newline="\n")

    index_file = coord_dir / "INDEX.md"
    index_file.write_text(CANONICAL_INDEX, encoding="utf-8", newline="\n")

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
def crlf_markdown_files(tmp_path: Path) -> Dict[str, Path]:
    """
    Creates coordination markdown files using strict Windows CRLF (\\r\\n) line endings.
    """
    crlf_dir = tmp_path / "crlf_coord"
    crlf_dir.mkdir(parents=True, exist_ok=True)

    board_content = CANONICAL_BOARD.replace("\n", "\r\n")
    questions_content = CANONICAL_QUESTIONS.replace("\n", "\r\n")
    handoffs_content = CANONICAL_HANDOFFS.replace("\n", "\r\n")
    index_content = CANONICAL_INDEX.replace("\n", "\r\n")

    board_file = crlf_dir / "BOARD.md"
    with open(board_file, "wb") as f:
        f.write(board_content.encode("utf-8"))

    questions_file = crlf_dir / "QUESTIONS.md"
    with open(questions_file, "wb") as f:
        f.write(questions_content.encode("utf-8"))

    handoffs_file = crlf_dir / "HANDOFFS.md"
    with open(handoffs_file, "wb") as f:
        f.write(handoffs_content.encode("utf-8"))

    index_file = crlf_dir / "INDEX.md"
    with open(index_file, "wb") as f:
        f.write(index_content.encode("utf-8"))

    return {
        "dir": crlf_dir,
        "board_file": board_file,
        "questions_file": questions_file,
        "handoffs_file": handoffs_file,
        "index_file": index_file
    }


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
    board_file.write_text(board_content, encoding="utf-8", newline="\n")

    questions_file = unicode_dir / "QUESTIONS.md"
    questions_file.write_text(questions_content, encoding="utf-8", newline="\n")

    handoffs_file = unicode_dir / "HANDOFFS.md"
    handoffs_file.write_text(handoffs_content, encoding="utf-8", newline="\n")

    return {
        "dir": unicode_dir,
        "board_file": board_file,
        "questions_file": questions_file,
        "handoffs_file": handoffs_file
    }
