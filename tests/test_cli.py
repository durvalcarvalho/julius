import os
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from julius.cli import app


def test_help_runs_and_names_the_tool():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Julius" in result.output


def test_no_arguments_prints_usage_instead_of_a_traceback():
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output


def test_importing_the_cli_has_no_side_effects_on_disk(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path), "JULIUS_DB": str(tmp_path / "x.db")}
    subprocess.run([sys.executable, "-c", "import julius.cli"], check=True, env=env, cwd=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_importing_the_cli_does_not_load_bot_dependencies():
    """cli e bot são irmãos que não se conhecem: pagar typer+rich ou telegram+pydantic_ai é
    escolha de quem entra, nunca herança de importar o outro."""
    code = "import julius.cli, sys; assert 'telegram' not in sys.modules and 'pydantic_ai' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.parametrize("group", ["mercados", "produtos"])
def test_a_command_group_alone_lists_its_commands(group):
    """Typing the group name is someone looking for what exists, not a mistake. The default
    "Missing command." box sent them to `--help` for the answer they had already asked for.

    Exit code stays 2, like `julius` alone: help was printed, but no command ran -- a script that
    reached here got no data."""
    result = CliRunner().invoke(app, [group])
    root = CliRunner().invoke(app, [])

    assert "Commands" in result.output
    assert "Missing command" not in result.output
    assert result.exit_code == root.exit_code == 2
