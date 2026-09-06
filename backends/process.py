"""Bounded lifetime for trusted native tools, including their POSIX process group.

This is cleanup, not a sandbox: deliberately detached/daemonized processes are outside
the group. The CLI runners execute on the main thread so SIGTERM can unwind cleanup.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _termination_unwinds():
    active = os.name == "posix" and threading.current_thread() is threading.main_thread()
    signals = (signal.SIGTERM, signal.SIGINT) if active else ()
    previous = {signum: signal.getsignal(signum) for signum in signals}
    pending = None
    armed = False

    def raise_pending():
        if pending == signal.SIGINT:
            raise KeyboardInterrupt
        if pending is not None:
            raise SystemExit(128 + pending)

    def terminate(signum, _frame):
        nonlocal pending
        pending = signum
        if armed:
            raise_pending()

    def arm():
        nonlocal armed
        # Delay cancellation until Popen has returned its handle into a protected try.
        armed = True
        raise_pending()

    def ignore_during_cleanup():
        for signum in signals:
            signal.signal(signum, signal.SIG_IGN)

    for signum in signals:
        signal.signal(signum, terminate)
    try:
        yield arm, ignore_during_cleanup
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _signal_group(process: subprocess.Popen[str], signum: int) -> None:
    # Popen(start_new_session=True) made this exact PID our group leader. Never
    # signal the caller's group, even if the immediate child has already exited.
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def _stop(process: subprocess.Popen[str]) -> tuple[str, str]:
    if os.name == "posix":
        _signal_group(process, signal.SIGTERM)
    elif process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False, capture_output=True, timeout=5,
        )
    try:
        process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # The leader can exit before a descendant that still holds our pipes.
        if os.name == "posix":
            _signal_group(process, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    return process.communicate(timeout=1)


def run_bounded(
    command: list[str], *, cwd: Path, timeout_seconds: int, label: str,
) -> subprocess.CompletedProcess[str]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    with _termination_unwinds() as (arm_cancellation, ignore_during_cleanup):
        process = None
        try:
            process = subprocess.Popen(
                command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
            arm_cancellation()
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            # Successful tools must not leave background helpers running either.
            if os.name == "posix":
                _signal_group(process, signal.SIGKILL)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except BaseException as error:
            if process is None:
                raise
            ignore_during_cleanup()
            stdout = stderr = ""
            try:
                stdout, stderr = _stop(process)
            except Exception as cleanup_error:
                # Keep cancellation/timeout as the primary failure, not a misleading
                # success or a different exception from the recovery path.
                note = f"Native process cleanup failed: {cleanup_error}"
                if hasattr(error, "add_note"):
                    error.add_note(note)
                else:  # Python 3.10 remains supported by this fork.
                    print(note, file=sys.stderr)
            if isinstance(error, subprocess.TimeoutExpired):
                failure = TimeoutError(
                    f"{label} exceeded {timeout_seconds}s; process cleanup attempted\n"
                    f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
                for note in getattr(error, "__notes__", ()):
                    failure.add_note(note)
                raise failure from error
            raise
        finally:
            if process is not None and process.stdout is not None:
                process.stdout.close()
            if process is not None and process.stderr is not None:
                process.stderr.close()
