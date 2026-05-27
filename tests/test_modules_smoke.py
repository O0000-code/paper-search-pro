"""Smoke tests for v2.0 post-refactor modules — verify import + --help.

These are the 7 modules that had SearchState removed in R1 + the federated KG
resolver that gained a CLI in the same wave. Each is checked twice:

  1. Module imports cleanly with no missing symbols (catches stale
     `from .types import SearchState` etc.).
  2. `python3 -m scripts.<name> --help` exits 0 (catches missing __main__
     blocks and argparse misconfigurations).
"""

import os
import subprocess
from pathlib import Path

import pytest

# Resolve the Skill root portably so contributors / CI can run these tests
# without first renaming themselves to `bo`. Priority:
#   1. PSP_SKILL_ROOT env var (CI / custom installs)
#   2. Walk up from __file__ to find the Skill root (works when tests/ is
#      checked out alongside scripts/ + SKILL.md, e.g. from a git clone)
#   3. The conventional Claude Code install location under the current user
SKILL = (
    Path(os.environ["PSP_SKILL_ROOT"]).expanduser()
    if os.environ.get("PSP_SKILL_ROOT")
    else (
        Path(__file__).resolve().parent.parent
        if (Path(__file__).resolve().parent.parent / "SKILL.md").exists()
        else Path("~/.claude/skills/paper-search-pro").expanduser()
    )
)
MODULES = [
    "data_materialization",
    "discovery_curve",
    "html_renderer_webartifacts",
    "md_report",
    "generate_exports",
    "prisma_s_logger",
    "federated_kg_resolver",
]


def _run(args):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=str(SKILL),
        timeout=30,
    )


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    result = _run(["python3", "-c", f"from scripts import {module}"])
    assert result.returncode == 0, (
        f"{module} failed to import. stderr=\n{result.stderr}"
    )


@pytest.mark.parametrize("module", MODULES)
def test_module_help(module):
    result = _run(["python3", "-m", f"scripts.{module}", "--help"])
    assert result.returncode == 0, (
        f"{module} --help failed. stderr=\n{result.stderr}"
    )
    # argparse always emits the program name on the first line of --help
    assert "usage" in result.stdout.lower(), (
        f"{module} --help did not look like argparse output. stdout=\n{result.stdout}"
    )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
