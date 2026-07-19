import subprocess
import sys
from pathlib import Path


def test_cloud_local_smoke_script():
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/cloud_local_smoke.py")],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "tombstone replay passed" in result.stdout
