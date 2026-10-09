"""The agent's v3 sources must be exactly what tools/sync_v3_sources.py generates from the training-side collector."""
import os
import subprocess
import sys

TOOL = os.path.join(os.path.dirname(__file__), "..", "tools", "sync_v3_sources.py")


def test_sources_in_sync():
    r = subprocess.run([sys.executable, TOOL, "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
