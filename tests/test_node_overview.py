"""Node-focused overview rules, independent of browser and live data."""
from pathlib import Path
import subprocess


def test_node_overview_contract():
    result = subprocess.run(
        ["node", "tests/test_node_overview.js"], capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, result.stdout + result.stderr
