"""sp7-camcheck.sh treats helper output as data and keeps its frames out of shared /tmp.

No camera is touched: pw-dump is replaced by a stub that prints a fixed graph.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMCHECK = os.path.join(ROOT, "camcheck", "sp7-camcheck.sh")
SNAPCHECK = os.path.join(ROOT, "camcheck", "snapcheck.py")


def script():
    with open(CAMCHECK) as f:
        return f.read()


def snapshot_graph(marker):
    """A running Snapshot stream fed by a node whose name tries to break out of a shell quote."""
    evil = f"cam'; touch {marker}; echo '"
    return [
        {"id": 1, "type": "PipeWire:Interface:Node",
         "info": {"state": "running", "props": {"media.class": "Stream/Input/Video", "application.name": "Snapshot"}}},
        {"id": 2, "type": "PipeWire:Interface:Node",
         "info": {"state": "running", "props": {"node.name": evil}}},
        {"id": 3, "type": "PipeWire:Interface:Link",
         "info": {"output-node-id": 2, "input-node-id": 1}},
    ]


def test_snapshot_check_does_not_run_node_names(tmp_path):
    marker = tmp_path / "injected"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(snapshot_graph(marker)))
    stub = bindir / "pw-dump"
    stub.write_text(f"#!/bin/sh\ncat '{graph}'\n")
    stub.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}")

    snap = subprocess.run([sys.executable, SNAPCHECK], capture_output=True, text=True, env=env)
    assert snap.returncode == 0, snap.stdout + snap.stderr
    assert "'" in snap.stdout

    line = next(ln.strip() for ln in script().splitlines() if ln.strip().startswith('check "Snapshot streaming'))
    harness = 'check() { shift; "$@"; }\nout=$(cat "$1")\n' + line + "\n"
    (tmp_path / "out.txt").write_text(snap.stdout)
    res = subprocess.run(["bash", "-c", harness, "harness", str(tmp_path / "out.txt")],
                         capture_output=True, text=True, cwd=tmp_path)
    assert not marker.exists(), "a PipeWire node name was executed as shell code"
    assert res.returncode == 0, res.stdout + res.stderr


def test_helper_output_never_spliced_into_bash_c():
    assert not re.search(r"""bash -c "[^"]*'\$out'""", script())


def test_frames_not_written_to_fixed_tmp_dir():
    s = script()
    assert not re.search(r"^OUT=/tmp/", s, re.M)
    assert re.search(r'^OUT=\$XDG_RUNTIME_DIR/', s, re.M)
