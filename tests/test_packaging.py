import importlib.util
import shutil
import subprocess
from pathlib import Path


def test_package_import_resolves_to_project_package():
    spec = importlib.util.find_spec("llm_fight")

    assert spec is not None
    assert spec.origin is not None
    assert Path(spec.origin).name == "__init__.py"


def test_console_script_help_uses_installed_entry_point():
    script = shutil.which("llmfight")

    assert script is not None, "llmfight console script is not installed in the active environment"

    result = subprocess.run(
        [script, "--help"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0
    assert "play" in output
    assert "simulate" in output
