"""Real process-lifetime regressions; no Blender/Godot launch is needed."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from backends.process import run_bounded


ROOT = Path(__file__).resolve().parents[3]
WRAPPER = r'''
import os, signal, subprocess, sys, time
from pathlib import Path
from backends.blender.runtime.run_backend import _run_blender
from integrations.godot.run_validation import _run_command
from backends import process as native_process

root, route, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
grandchild = """
import os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
print('retained child diagnostic', flush=True)
time.sleep(60)
"""
child = """
import os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
root.joinpath('parent.pid').write_text(str(os.getpid()))
output = subprocess.DEVNULL if sys.argv[2] == 'success-terminate' else None
subprocess.Popen([sys.executable, '-c', sys.argv[3], str(root / 'child.pid')],
                 stdout=output, stderr=output)
while not (root / 'child.pid').exists():
    time.sleep(0.01)
if sys.argv[2] in ('leader-exits', 'success-terminate'):
    sys.exit(0)
time.sleep(60)
"""
command = [sys.executable, '-c', child, str(root), mode, grandchild]
if mode == 'launch-terminate':
    original_popen = subprocess.Popen
    def launch(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        while not (root / 'child.pid').exists():
            time.sleep(0.01)
        os.kill(os.getpid(), signal.SIGTERM)
        return process
    subprocess.Popen = launch
if mode == 'success-terminate':
    original_signal_group = native_process._signal_group
    terminated = False
    def signal_group(process, signum):
        global terminated
        if signum == signal.SIGKILL and not terminated:
            terminated = True
            os.kill(os.getpid(), signal.SIGTERM)
        original_signal_group(process, signum)
    native_process._signal_group = signal_group
if mode == 'interrupt':
    original_communicate = subprocess.Popen.communicate
    interrupted = False
    def communicate(process, *args, **kwargs):
        global interrupted
        if not interrupted:
            while not (root / 'child.pid').exists():
                time.sleep(0.01)
            interrupted = True
            raise KeyboardInterrupt('original cancellation')
        return original_communicate(process, *args, **kwargs)
    subprocess.Popen.communicate = communicate
old_handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
try:
    if route == 'blender':
        _run_blender(command, cwd=root, timeout_seconds=20 if mode == 'terminate' else 1)
    else:
        _run_command(command, root, 20 if mode == 'terminate' else 1)
except TimeoutError as error:
    print('TIMEOUT:', error)
except KeyboardInterrupt as error:
    print('INTERRUPTED:', error)
finally:
    assert all(signal.getsignal(sig) == handler for sig, handler in old_handlers.items()), 'signal handler leaked'
'''


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux process-group lifecycle")
class NativeProcessTests(unittest.TestCase):
    @staticmethod
    def _running(pid: int) -> bool:
        try:
            # An orphan may await init's reap briefly; a zombie cannot hold pipes or run.
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except FileNotFoundError:
            return False

    @staticmethod
    def _kill(pid: int) -> None:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _case(self, route: str, mode: str) -> None:
        with tempfile.TemporaryDirectory(prefix="forge-process-test-", dir="/var/tmp") as directory:
            root = Path(directory)
            sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                        start_new_session=True)
            wrapper = subprocess.Popen([sys.executable, "-c", WRAPPER, directory, route, mode],
                                       cwd=ROOT, start_new_session=True, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                if mode == "terminate":
                    deadline = time.monotonic() + 5
                    while not (root / "child.pid").exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue((root / "child.pid").exists(), "fixture did not start")
                    # Exactly how the Factory cancels its owned Python-wrapper group.
                    os.killpg(wrapper.pid, signal.SIGTERM)
                output, errors = wrapper.communicate(timeout=8)
                expected_exit = 143 if "terminate" in mode else 0
                self.assertEqual(wrapper.returncode, expected_exit, output + errors)
                if mode == "interrupt":
                    self.assertIn("INTERRUPTED: original cancellation", output)
                elif "terminate" not in mode:
                    self.assertIn("TIMEOUT:", output)
                    self.assertIn("retained child diagnostic", output)
                for name in ("parent.pid", "child.pid"):
                    pid = int((root / name).read_text())
                    deadline = time.monotonic() + 1
                    while self._running(pid) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertFalse(self._running(pid), f"{name} survived {mode}: {pid}")
                self.assertIsNone(sentinel.poll(), "cleanup killed an unrelated process")
            finally:
                # Outer watchdog cleanup remains effective even against the old broken runner.
                for name in ("parent.pid", "child.pid"):
                    if (root / name).exists():
                        self._kill(int((root / name).read_text()))
                if wrapper.poll() is None:
                    self._kill(wrapper.pid)
                wrapper.communicate(timeout=3)
                sentinel.kill()
                sentinel.wait(timeout=3)

    def test_timeout_cleans_both_native_routes(self) -> None:
        for route in ("blender", "godot"):
            with self.subTest(route=route):
                self._case(route, "timeout")

    def test_cleanup_after_leader_has_exited(self) -> None:
        for route in ("blender", "godot"):
            with self.subTest(route=route):
                self._case(route, "leader-exits")

    def test_original_interrupt_survives_cleanup(self) -> None:
        for route in ("blender", "godot"):
            with self.subTest(route=route):
                self._case(route, "interrupt")

    def test_factory_style_termination_reaches_isolated_children(self) -> None:
        for route in ("blender", "godot"):
            with self.subTest(route=route):
                self._case(route, "terminate")

    def test_success_preserves_output_and_return_code(self) -> None:
        result = run_bounded(
            [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)"],
            cwd=ROOT, timeout_seconds=5, label="test",
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (7, "out\n", "err\n"))

    def test_termination_at_launch_and_success_boundaries(self) -> None:
        self._case("blender", "launch-terminate")
        self._case("godot", "success-terminate")

    def test_rejects_nonpositive_timeout(self) -> None:
        with self.assertRaises(ValueError):
            run_bounded([], cwd=ROOT, timeout_seconds=0, label="test")


if __name__ == "__main__":
    unittest.main()
