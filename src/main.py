"""
Agent Orchestrator — Entry Point
================================
Version 1.0 — November 2025

Main entry point for the orchestrator.
"""

import argparse
import sys
import os
import asyncio
import signal
import atexit
import traceback as _traceback
import logging

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Disable LangSmith tracing by default to prevent warnings
if "LANGCHAIN_TRACING_V2" not in os.environ:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langgraph_definition import create_orchestrator, start_run
from config import OrchestratorConfig, ModelConfig

# Configure basic logging for crash detection
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")


class Tee:
    """
    A file-like object that writes to multiple destinations.

    Properly implements all necessary file object methods to avoid
    terminal corruption when used as stdout/stderr replacement.
    """
    def __init__(self, *files):
        self.files = files
        # Store reference to original terminal for isatty check
        self._terminal = files[0] if files else None

    def write(self, obj):
        for f in self.files:
            try:
                f.write(obj)
                f.flush()
            except (ValueError, IOError):
                # File might be closed, ignore
                pass

    def flush(self):
        for f in self.files:
            try:
                f.flush()
            except (ValueError, IOError):
                pass

    def isatty(self):
        """Return True if the first file (terminal) is a tty."""
        if self._terminal and hasattr(self._terminal, 'isatty'):
            try:
                return self._terminal.isatty()
            except (ValueError, IOError):
                return False
        return False

    def fileno(self):
        """Return file descriptor of the terminal if available."""
        if self._terminal and hasattr(self._terminal, 'fileno'):
            try:
                return self._terminal.fileno()
            except (ValueError, IOError):
                raise OSError("Stream does not have a file descriptor")
        raise OSError("Stream does not have a file descriptor")

    @property
    def encoding(self):
        """Return encoding of the first file."""
        if self._terminal and hasattr(self._terminal, 'encoding'):
            return self._terminal.encoding
        return 'utf-8'

    @property
    def errors(self):
        """Return error handling mode."""
        if self._terminal and hasattr(self._terminal, 'errors'):
            return self._terminal.errors
        return 'replace'

    @property
    def mode(self):
        """Return mode string."""
        return 'w'

    @property
    def name(self):
        """Return name of the stream."""
        if self._terminal and hasattr(self._terminal, 'name'):
            return self._terminal.name
        return '<tee>'

    @property
    def closed(self):
        """Return True if all files are closed."""
        return all(getattr(f, 'closed', True) for f in self.files)

    def close(self):
        """Close all files except the original terminal."""
        for f in self.files[1:]:  # Skip terminal (first file)
            try:
                if hasattr(f, 'close') and not getattr(f, 'closed', True):
                    f.close()
            except (ValueError, IOError):
                pass

    def readable(self):
        return False

    def writable(self):
        return True

    def seekable(self):
        return False


# =============================================================================
# CRASH DETECTION - Diagnose Silent Failures
# =============================================================================

_original_stdout = None
_original_stderr = None
_log_file_handle = None


def _restore_stdio():
    """Restore original stdout/stderr."""
    global _original_stdout, _original_stderr, _log_file_handle

    if _original_stdout is not None:
        sys.stdout = _original_stdout
        _original_stdout = None
    if _original_stderr is not None:
        sys.stderr = _original_stderr
        _original_stderr = None
    if _log_file_handle is not None:
        try:
            _log_file_handle.flush()
            _log_file_handle.close()
        except (ValueError, IOError):
            pass
        _log_file_handle = None


def _signal_handler(sig, frame):
    """Log signals that would terminate the program."""
    signal_name = signal.Signals(sig).name
    logger.error(f"🚨 SIGNAL RECEIVED: {signal_name} (code {sig})")
    logger.error(f"   Stack trace at signal:")
    for line in _traceback.format_stack(frame):
        logger.error(f"     {line.strip()}")

    # Restore stdio before exiting
    _restore_stdio()

    # Re-raise to allow default handling
    logger.error(f"   Program will now exit due to {signal_name}")
    signal.signal(sig, signal.SIG_DFL)
    os.kill(os.getpid(), sig)


def _atexit_handler():
    """Log when Python is exiting and restore terminal."""
    logger.info("🔚 Program exiting - cleaning up...")
    _restore_stdio()


def _asyncio_exception_handler(loop, context):
    """Log unhandled exceptions in asyncio tasks."""
    logger.error("🚨 ASYNCIO UNHANDLED EXCEPTION:")
    logger.error(f"   Message: {context.get('message', 'Unknown')}")

    exception = context.get('exception')
    if exception:
        logger.error(f"   Exception type: {type(exception).__name__}")
        logger.error(f"   Exception: {exception}")
        logger.error(f"   Traceback:")
        for line in _traceback.format_exception(type(exception), exception, exception.__traceback__):
            logger.error(f"     {line.rstrip()}")

    task = context.get('task')
    if task:
        logger.error(f"   Failed task: {task}")


# Register handlers
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, _signal_handler)
atexit.register(_atexit_handler)

# =============================================================================
# END CRASH DETECTION
# =============================================================================


async def main():
    """Main entry point (async version)."""
    global _original_stdout, _original_stderr, _log_file_handle

    parser = argparse.ArgumentParser(description="Agent Orchestrator")
    parser.add_argument("--objective", type=str, default="Build a simple API", help="What to build")
    parser.add_argument("--workspace", type=str, default="projects/workspace",
                       help="Directory where the project will be built (default: projects/workspace)")
    parser.add_argument("--mock-run", action="store_true", help="Run in mock mode (no LLM)")
    parser.add_argument("--provider", type=str, default="openai",
                       choices=["openai", "anthropic", "google", "glm", "openrouter"],
                       help="LLM provider (default: openai)")
    parser.add_argument("--model", type=str, help="Model name (e.g., gpt-4o, claude-3-5-sonnet-20241022)")

    args = parser.parse_args()

    # Set asyncio exception handler
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_asyncio_exception_handler)

    # Setup logging
    import datetime

    # Create logs directory in the workspace
    workspace_path = os.path.abspath(args.workspace)
    log_dir = os.path.join(workspace_path, "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Create log file with timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"run_{timestamp}.log")

    # Open log file and redirect stdout/stderr
    _log_file_handle = open(log_file, 'w', encoding='utf-8')
    _original_stdout = sys.stdout
    _original_stderr = sys.stderr

    sys.stdout = Tee(sys.stdout, _log_file_handle)
    sys.stderr = Tee(sys.stderr, _log_file_handle)

    print(f"Logging to: {log_file}")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    # Disable LangSmith tracing by default (unless explicitly enabled)
    if "LANGCHAIN_TRACING_V2" not in os.environ:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

    # Determine model configuration
    if args.model:
        # User specified model via CLI
        model_name = args.model
    else:
        # Use defaults from config.py (respects user's config.py edits)
        default_config = OrchestratorConfig()
        if args.provider == "openai":
            model_name = default_config.worker_model.model_name if default_config.worker_model.provider == "openai" else "gpt-4.1"
        elif args.provider == "anthropic":
            model_name = default_config.worker_model.model_name if default_config.worker_model.provider == "anthropic" else "claude-3-5-sonnet-20241022"
        elif args.provider == "google":
            model_name = "gemini-1.5-pro"
        elif args.provider == "glm":
            model_name = "glm-4-plus"  # Default GLM model
        elif args.provider == "openrouter":
            model_name = "anthropic/claude-3.5-sonnet"  # Default OpenRouter model
        else:
            model_name = "gpt-4.1"  # Fallback
    
    # Load base config from config.py (respects user's settings)
    base_config = OrchestratorConfig()
    
    # Only override if user explicitly passed --provider or --model
    # If they didn't specify, respect config.py settings
    if args.model or args.provider != "openai":  # "openai" is the default, so if it's that, user didn't specify
        # User wants to override - apply to all models
        config = OrchestratorConfig(
            director_model=ModelConfig(
                provider=args.provider,
                model_name=model_name,
                temperature=0.7
            ),
            worker_model=ModelConfig(
                provider=args.provider,
                model_name=model_name,
                temperature=0.5
            ),
            strategist_model=ModelConfig(
                provider=args.provider,
                model_name=model_name,
                temperature=0.3
            ),
            mock_mode=args.mock_run
        )
    else:
        # No CLI override - use config.py settings
        config = base_config
        config.mock_mode = args.mock_run

    
    print(f"\n{'='*60}")
    print(f"AGENT ORCHESTRATOR")
    print(f"{'='*60}")
    print(f"Objective: {args.objective}")
    print(f"Workspace: {args.workspace}")
    print(f"Provider: {args.provider}")
    print(f"Model: {model_name}")
    print(f"Mock Mode: {args.mock_run}")
    print(f"{'='*60}\n")
    
    # Run orchestrator
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        
        # Setup persistent DB
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "orchestrator.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        
        # We need to pass checkpointer to start_run, but start_run currently calls create_orchestrator internally.
        # We should modify start_run to accept checkpointer or modify create_orchestrator call inside it.
        # Actually, start_run in langgraph_definition.py calls create_orchestrator(config).
        # We need to modify start_run in langgraph_definition.py to accept checkpointer too.
        # For now, let's just modify start_run in langgraph_definition.py as well.
        
        # Wait, I can't modify langgraph_definition.py from here.
        # I should have modified start_run in langgraph_definition.py earlier.
        # Let's check langgraph_definition.py content again.
        
        result = await start_run(
            objective=args.objective,
            workspace=args.workspace,
            config=config,
            checkpointer=checkpointer
        )
        
        print(f"\n{'='*60}")
        
        # Check if paused vs actually complete
        if result.get("_paused_for_hitl"):
            logger.info("RUN PAUSED FOR HUMAN INPUT")
            logger.info(f"{'='*60}")
            logger.info("Open the dashboard to resolve:")
            logger.info("   http://localhost:3000")
            logger.info("   The run will resume after you provide input.")
        else:
            logger.info("RUN COMPLETE")
            logger.info(f"{'='*60}")
        
        tasks = result.get('tasks', [])
        print(f"Total tasks: {len(tasks)}")
        for t in tasks:
            status_icon = "[OK]" if t.get('status') == 'complete' else "[X]"
            print(f"{status_icon} {t.get('id')}: {t.get('status')} - {t.get('description')}")
            
        completed = [t for t in tasks if t.get('status') == 'complete']
        print(f"\nTasks completed: {len(completed)}/{len(tasks)}")
        
        return 0
        
    except Exception as e:
        logger.error(f"💥 FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # CRITICAL: Always restore stdout/stderr and close log file
        # This prevents terminal corruption on any exit path
        logger.info("🔚 Cleaning up resources...")
        _restore_stdio()
        logger.info("✅ Cleanup complete")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
