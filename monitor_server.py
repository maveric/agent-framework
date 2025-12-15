"""
External Server Monitor
=======================
Monitors the server process externally to catch silent failures.

This script spawns the server as a subprocess and monitors it:
- Captures the exit code when process dies
- Logs memory usage periodically
- Records the exact time of death
- Works even if Python's internal logging fails

Usage:
    python monitor_server.py
"""

import subprocess
import sys
import os
import time
import signal
from datetime import datetime
from pathlib import Path

# Log file for monitoring
MONITOR_LOG = Path(__file__).parent / "monitor.log"
DIAGNOSTIC_LOG = Path(__file__).parent / "exit_diagnostic.log"


def log(msg: str):
    """Log with timestamp to file and console."""
    timestamp = datetime.now().isoformat()
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(MONITOR_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


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
    log("=" * 60)
    log("EXTERNAL SERVER MONITOR STARTING")
    log("=" * 60)
    
    # Clear previous diagnostic log
    if DIAGNOSTIC_LOG.exists():
        with open(DIAGNOSTIC_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat()}] --- MONITOR STARTING NEW SESSION ---\n")
    
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
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(Path(__file__).parent),
            bufsize=1,
            universal_newlines=True,
        )
    except Exception as e:
        log(f"ERROR: Failed to start server: {e}")
        sys.exit(1)
    
    log(f"Server started with PID: {proc.pid}")
    
    # Monitor loop
    last_heartbeat = time.time()
    heartbeat_interval = 5  # Log memory every 5 seconds
    
    try:
        while True:
            # Check if process is still running
            retcode = proc.poll()
            
            if retcode is not None:
                # Process died!
                death_time = datetime.now().isoformat()
                log("!" * 60)
                log(f"PROCESS DIED at {death_time}")
                log(f"Exit code: {format_exit_code(retcode)}")
                log("!" * 60)
                
                # Capture any remaining output
                remaining_output = proc.stdout.read() if proc.stdout else ""
                if remaining_output:
                    log("Final output:")
                    for line in remaining_output.splitlines()[-50:]:  # Last 50 lines
                        log(f"  {line}")
                
                # Check the diagnostic log
                if DIAGNOSTIC_LOG.exists():
                    log("Contents of exit_diagnostic.log:")
                    with open(DIAGNOSTIC_LOG, "r", encoding="utf-8") as f:
                        for line in f.read().splitlines()[-30:]:  # Last 30 lines
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
                    log("  → Check the process log files in projects/workspace/logs/")
                
                break
            
            # Read any available output (non-blocking)
            try:
                line = proc.stdout.readline()
                if line:
                    print(line.rstrip())  # Echo to console
            except:
                pass
            
            # Periodic heartbeat with memory info
            if time.time() - last_heartbeat > heartbeat_interval:
                mem = get_memory_info(proc.pid)
                if "error" not in mem:
                    log(f"HEARTBEAT: PID={proc.pid}, RSS={mem['rss_mb']:.1f}MB, VMS={mem['vms_mb']:.1f}MB")
                last_heartbeat = time.time()
            
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
    except Exception as e:
        # Catch-all for any unexpected errors in the MONITOR ITSELF
        import traceback
        log("!" * 60)
        log(f"MONITOR SCRIPT ERROR: {type(e).__name__}: {e}")
        log("Monitor traceback:")
        for line in traceback.format_exc().split('\n'):
            log(f"  {line}")
        log("!" * 60)
        
        # Still try to kill the subprocess if it's running
        if proc and proc.poll() is None:
            log("Killing server subprocess due to monitor error...")
            proc.kill()


if __name__ == "__main__":
    main()
