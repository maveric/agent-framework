"""
External Server Monitor
=======================
Monitors the server process externally to catch silent failures.

This script spawns the server as a subprocess and monitors it:
- Captures the exit code when process dies
- Logs memory usage periodically
- Records the exact time of death
- Works even if Python's internal logging fails
- Uses non-blocking I/O to prevent readline() hangs
- Includes Windows-specific handling for console events

Usage:
    python monitor_server.py
"""

import subprocess
import sys
import os
import time
import signal
import threading
import atexit
from datetime import datetime
from pathlib import Path
import platform

# Log file for monitoring
MONITOR_LOG = Path(__file__).parent / "monitor.log"
DIAGNOSTIC_LOG = Path(__file__).parent / "exit_diagnostic.log"
WATCHDOG_FILE = Path(__file__).parent / "watchdog.log"

# Global state for watchdog
_watchdog_running = True
_last_activity = time.time()
_proc_ref = None


def log(msg: str):
    """Log with timestamp to file and console."""
    timestamp = datetime.now().isoformat()
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    try:
        with open(MONITOR_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())  # Force OS write
    except Exception:
        pass  # Don't fail logging


def _write_watchdog():
    """Write watchdog timestamp - survives even if main thread dies."""
    global _watchdog_running, _last_activity, _proc_ref

    while _watchdog_running:
        try:
            proc_status = "unknown"
            proc_code = "N/A"
            if _proc_ref:
                poll_result = _proc_ref.poll()
                if poll_result is None:
                    proc_status = "running"
                else:
                    proc_status = "dead"
                    proc_code = str(poll_result)

            with open(WATCHDOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] WATCHDOG: proc={proc_status}, code={proc_code}, last_activity={time.time() - _last_activity:.1f}s ago\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            pass  # Never fail watchdog

        time.sleep(2)  # Write every 2 seconds


def _emergency_exit_handler():
    """Called on ANY exit - atexit, signal, etc."""
    try:
        with open(DIAGNOSTIC_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat()}] EMERGENCY EXIT HANDLER TRIGGERED\n")
            f.write(f"   _proc_ref exists: {_proc_ref is not None}\n")
            if _proc_ref:
                poll = _proc_ref.poll()
                f.write(f"   subprocess poll: {poll}\n")
                if poll is not None:
                    f.write(f"   subprocess returncode: {_proc_ref.returncode}\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass


def get_memory_info(pid: int) -> dict:
    """Get memory info for a process (Windows-compatible)."""
    try:
        import psutil
        proc = psutil.Process(pid)
        mem = proc.memory_info()
        return {
            "rss_mb": mem.rss / (1024 * 1024),
            "vms_mb": mem.vms / (1024 * 1024),
        }
    except Exception as e:
        return {"error": str(e)}


def format_exit_code(code: int) -> str:
    """Format exit code with Windows and Linux-specific interpretation."""
    import platform
    
    if code == 0:
        return "0 (Success)"
    elif code > 0:
        return f"{code} (Application error)"
    else:
        # Negative codes differ by platform
        if platform.system() == "Windows":
            # Windows: Negative codes are often NTSTATUS codes
            unsigned = code & 0xFFFFFFFF
            
            known_codes = {
                0xC0000005: "ACCESS_VIOLATION (Segfault)",
                0xC00000FD: "STACK_OVERFLOW",
                0xC0000094: "INTEGER_DIVIDE_BY_ZERO",
                0xC0000135: "DLL_NOT_FOUND",
                0xC0000142: "DLL_INIT_FAILED",
                0xC000013A: "CONTROL_C_EXIT (Ctrl+C)",
                0x80000003: "BREAKPOINT",
                0xE0434352: ".NET_EXCEPTION",
            }
            
            if unsigned in known_codes:
                return f"{code} ({hex(unsigned)}: {known_codes[unsigned]})"
            else:
                return f"{code} ({hex(unsigned)}: Unknown Windows exception)"
        else:
            # Linux: Negative code = killed by signal
            # Exit code is -(signal_number)
            signal_num = -code
            
            # Common signals
            signals = {
                1: "SIGHUP (Hangup)",
                2: "SIGINT (Interrupt/Ctrl+C)",
                3: "SIGQUIT (Quit)",
                4: "SIGILL (Illegal instruction)",
                6: "SIGABRT (Abort)",
                8: "SIGFPE (Floating point exception)",
                9: "SIGKILL (Killed - untrappable!)",
                11: "SIGSEGV (Segmentation fault)",
                13: "SIGPIPE (Broken pipe)",
                14: "SIGALRM (Alarm)",
                15: "SIGTERM (Terminated)",
            }
            
            if signal_num in signals:
                return f"{code} (Signal {signal_num}: {signals[signal_num]})"
            else:
                return f"{code} (Signal {signal_num}: Unknown signal)"


def main():
    global _watchdog_running, _proc_ref, _last_activity

    log("=" * 60)
    log("EXTERNAL SERVER MONITOR STARTING")
    log(f"Platform: {platform.system()} {platform.release()}")
    log(f"Python: {sys.version}")
    log("=" * 60)

    # Register emergency exit handler FIRST
    atexit.register(_emergency_exit_handler)

    # Clear/initialize watchdog file
    with open(WATCHDOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] WATCHDOG STARTED\n")
        f.flush()
        os.fsync(f.fileno())

    # Start watchdog thread
    watchdog_thread = threading.Thread(target=_write_watchdog, daemon=True)
    watchdog_thread.start()
    log("Watchdog thread started")

    # Clear previous diagnostic log
    with open(DIAGNOSTIC_LOG, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now().isoformat()}] --- MONITOR STARTING NEW SESSION ---\n")
        f.write(f"   Platform: {platform.system()} {platform.release()}\n")
        f.write(f"   Python: {sys.version}\n")
        f.flush()
        os.fsync(f.fileno())

    # Build command to run the server
    server_script = Path(__file__).parent / "src" / "server.py"

    if not server_script.exists():
        log(f"ERROR: Server script not found at {server_script}")
        sys.exit(1)

    cmd = [sys.executable, str(server_script)]
    log(f"Starting server: {' '.join(cmd)}")

    # Start the server process
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # Disable Python output buffering

    # Windows-specific: Create process with proper flags
    creation_flags = 0
    if platform.system() == "Windows":
        # CREATE_NEW_PROCESS_GROUP: Allows us to kill just this process tree
        # without affecting the parent console
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(Path(__file__).parent),
            bufsize=1,
            universal_newlines=True,
            creationflags=creation_flags,
        )
        _proc_ref = proc  # For watchdog
    except Exception as e:
        log(f"ERROR: Failed to start server: {e}")
        sys.exit(1)

    log(f"Server started with PID: {proc.pid}")

    # Windows doesn't support select() on file handles, only sockets
    # Use a separate thread for reading stdout instead
    import queue
    output_queue = queue.Queue()

    def _read_output():
        """Read stdout in a separate thread to avoid blocking."""
        try:
            while True:
                line = proc.stdout.readline()
                if line:
                    output_queue.put(line.rstrip())
                elif proc.poll() is not None:
                    # Process died and no more output
                    break
        except Exception as e:
            output_queue.put(f"[READ ERROR: {e}]")

    reader_thread = threading.Thread(target=_read_output, daemon=True)
    reader_thread.start()

    # Monitor loop
    last_heartbeat = time.time()
    heartbeat_interval = 5  # Log memory every 5 seconds
    lines_since_heartbeat = 0

    try:
        while True:
            _last_activity = time.time()  # Update for watchdog

            # Check if process is still running
            retcode = proc.poll()

            if retcode is not None:
                # Process died!
                death_time = datetime.now().isoformat()
                log("!" * 60)
                log(f"PROCESS DIED at {death_time}")
                log(f"Exit code: {format_exit_code(retcode)}")
                log("!" * 60)

                # Write to diagnostic log immediately
                with open(DIAGNOSTIC_LOG, "a", encoding="utf-8") as f:
                    f.write(f"\n[{death_time}] SUBPROCESS DEATH DETECTED\n")
                    f.write(f"   Exit code: {format_exit_code(retcode)}\n")
                    f.flush()
                    os.fsync(f.fileno())

                # Drain any remaining output from queue
                while not output_queue.empty():
                    try:
                        line = output_queue.get_nowait()
                        print(line, flush=True)
                    except queue.Empty:
                        break

                # Check the diagnostic log
                if DIAGNOSTIC_LOG.exists():
                    log("Contents of exit_diagnostic.log:")
                    with open(DIAGNOSTIC_LOG, "r", encoding="utf-8") as f:
                        for line in f.read().splitlines()[-30:]:  # Last 30 lines
                            log(f"  {line}")

                # Check watchdog log
                if WATCHDOG_FILE.exists():
                    log("Last watchdog entries:")
                    with open(WATCHDOG_FILE, "r", encoding="utf-8") as f:
                        for line in f.read().splitlines()[-10:]:
                            log(f"  {line}")

                # Suggest next steps based on exit code
                log("")
                log("NEXT STEPS TO DIAGNOSE:")
                if retcode < 0:
                    unsigned = retcode & 0xFFFFFFFF
                    if unsigned == 0xC0000005:
                        log("  → ACCESS_VIOLATION: Check for native code issues (numpy, C extensions)")
                        log("  → Run with: python -X faulthandler src/server.py")
                    elif unsigned == 0xC00000FD:
                        log("  → STACK_OVERFLOW: Check for infinite recursion")
                    else:
                        log("  → Unknown Windows exception. Check Windows Event Viewer:")
                        log("     Event Viewer → Windows Logs → Application")
                else:
                    log("  → Check exit_diagnostic.log for last heartbeat")
                    log("  → Check watchdog.log for activity timeline")
                    log("  → Check the process log files in projects/workspace/logs/")

                break

            # Read any available output from queue (non-blocking)
            try:
                while True:
                    line = output_queue.get_nowait()
                    print(line, flush=True)
                    lines_since_heartbeat += 1
            except queue.Empty:
                pass  # No more output available

            # Periodic heartbeat with memory info
            if time.time() - last_heartbeat > heartbeat_interval:
                mem = get_memory_info(proc.pid)
                if "error" not in mem:
                    log(f"HEARTBEAT: PID={proc.pid}, RSS={mem['rss_mb']:.1f}MB, VMS={mem['vms_mb']:.1f}MB, lines={lines_since_heartbeat}")
                else:
                    log(f"HEARTBEAT: PID={proc.pid}, mem_error={mem.get('error', 'unknown')}, lines={lines_since_heartbeat}")
                last_heartbeat = time.time()
                lines_since_heartbeat = 0

            # Small sleep to prevent busy loop
            time.sleep(0.1)

    except KeyboardInterrupt:
        # Check if subprocess is still alive
        # On Windows, subprocess death can sometimes raise KeyboardInterrupt
        if proc.poll() is None:
            # Process still running - this is a real Ctrl+C
            log("Monitor interrupted by user (Ctrl+C)")
            log("Terminating server...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log("Server didn't terminate, killing...")
                proc.kill()
        else:
            # Process already dead - not a real Ctrl+C, subprocess crashed
            log("Server process terminated unexpectedly (triggered KeyboardInterrupt)")
            log(f"Exit code: {format_exit_code(proc.returncode)}")
            log("This is NOT a user Ctrl+C - the subprocess crashed first")

    except BaseException as e:
        # Catch EVERYTHING including SystemExit, GeneratorExit, etc.
        # This is critical for debugging silent exits
        import traceback
        log("!" * 60)
        log(f"MONITOR BASE EXCEPTION: {type(e).__name__}: {e}")
        log("Monitor traceback:")
        for tb_line in traceback.format_exc().split('\n'):
            log(f"  {tb_line}")
        log("!" * 60)

        # Write to diagnostic log
        with open(DIAGNOSTIC_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat()}] BASE EXCEPTION IN MONITOR\n")
            f.write(f"   Type: {type(e).__name__}\n")
            f.write(f"   Message: {e}\n")
            f.write(f"   Traceback: {traceback.format_exc()}\n")
            f.flush()
            os.fsync(f.fileno())

        # Still try to kill the subprocess if it's running
        if proc and proc.poll() is None:
            log("Killing server subprocess due to monitor error...")
            proc.kill()

        # Re-raise if it's something we shouldn't suppress
        if isinstance(e, (SystemExit, KeyboardInterrupt)):
            raise

    finally:
        _watchdog_running = False
        log("Monitor shutdown complete")


if __name__ == "__main__":
    main()
