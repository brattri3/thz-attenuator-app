"""
test_dashboard_module.py - import-level checks for dashboard.py against a stub streamlit.

The UI cannot be driven headlessly here, but the things that went wrong in issue #6 are not
rendering bugs: they are a hidden control, a default, a hardcoded path and a second INDEX.md
generator. All of those are visible in the module source and in its pure helpers, so they
are checked rather than left to a manual pass.
"""

import re
import sys
import types
from pathlib import Path

import pytest

DASHBOARD_PY = Path(__file__).resolve().parent.parent / "dashboard.py"
SOURCE = DASHBOARD_PY.read_text(encoding="utf-8")


@pytest.fixture
def stub_streamlit(monkeypatch):
    """A streamlit stand-in that records nothing and tolerates any call.

    Enough to let dashboard.py import; not enough to render. Only import-time behaviour and
    module-level structure are asserted against it.
    """
    module = types.ModuleType("streamlit")

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _any_call(*args, **kwargs):
        return _Ctx()

    module.__getattr__ = lambda name: _any_call  # type: ignore[attr-defined]
    module.session_state = {}
    module.columns = lambda spec, **kw: [_Ctx() for _ in (range(spec) if isinstance(spec, int) else spec)]
    monkeypatch.setitem(sys.modules, "streamlit", module)
    return module


def test_dashboard_imports_with_streamlit_present(stub_streamlit):
    import importlib

    spec = importlib.util.spec_from_file_location("dashboard_under_test", DASHBOARD_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "render_diagnostics")
    assert hasattr(module, "discover_coordination_dir")

    # The write path is gone, and these names are how it would grow back: a stager, a
    # confirm step, and the commit helper they fed. Absence is the property under test.
    for removed in ("request_write", "render_pending_write", "handle_mutation_and_commit",
                    "rebuild_index_file"):
        assert not hasattr(module, removed), (
            "%s is back; this module reads and does not write" % removed
        )


def test_the_sidebar_is_gone():
    """st.sidebar does not render under some Streamlit versions (reporter saw 1.62).

    The git auto-commit toggle lived there AND defaulted to on, so it was an unreachable
    control that was enabled by default.
    """
    code = re.sub(r"#.*", "", SOURCE)
    assert "st.sidebar" not in code


def test_there_is_no_git_commit_control():
    """There is nothing to commit from here, so there is no toggle to get wrong.

    The toggle this replaces was the issue #6 finding twice over: it lived in a sidebar that
    some Streamlit versions do not render, and it defaulted to on. Both problems are solved
    by the control not existing.
    """
    code = re.sub(r"#.*", "", SOURCE)
    assert "Commit changes to git" not in code
    assert "COORDINATION_DASHBOARD_WRITES" not in code


def test_nothing_here_opens_a_file_for_writing():
    """A read-only view is checkable, and a gated writer is not the same thing.

    The previous version of this test asserted every write button carried
    `disabled=not writes_on` -- a real check, but one that assumes the buttons exist and
    only asks whether they are gated. There is no gate to audit now: the module opens no
    file for writing and runs no git subprocess.
    """
    code = re.sub(r"#.*", "", SOURCE)
    for writer in ('open(', 'write_text', 'subprocess'):
        if writer == 'open(':
            for match in re.findall(r'open\([^)]*', code):
                assert '"r"' in match or "mode=" not in match, match
                assert '"w"' not in match and "'w'" not in match, match
        else:
            assert writer not in code, "%s has no place in a read-only view" % writer


def test_the_hardcoded_role_roster_is_gone():
    """The source project's roster was baked into a template."""
    for leaked in ("qa_tester", "physics"):
        assert f'"{leaked}"' not in SOURCE, f"{leaked} is another project's role"


def test_the_worktree_cd_hint_is_not_hardcoded():
    assert "cd assets/.worktrees/" not in SOURCE


def test_index_is_not_generated_here_at_all():
    """Two generators once wrote the same filename in different formats.

    That was settled by routing this module through `build_index.build_index_text`. It is
    settled harder now: the module reads INDEX.md if it is there and otherwise names the
    command that builds it, so there is no second implementation and no second writer.
    """
    assert "## QUESTIONS.md — open" not in SOURCE, (
        "dashboard.py must not render INDEX.md sections itself"
    )
    code = re.sub(r"#.*", "", SOURCE)
    assert "import build_index" not in code
    assert "build_index_text" not in code, (
        "the generator is a CLI the reader runs, not an import this module calls"
    )
