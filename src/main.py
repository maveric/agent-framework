"""
Agent Orchestrator — Entry Point
================================
Version 1.0 — November 2025

Main entry point for the orchestrator.
"""

import argparse
import sys
import os

# Add src to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Disable LangSmith tracing by default to prevent warnings
if "LANGCHAIN_TRACING_V2" not in os.environ:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langgraph_definition import create_orchestrator, start_run
from config import OrchestratorConfig, ModelConfig


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Agent Orchestrator")
    parser.add_argument("--objective", type=str, default="Build a simple API", help="What to build")
    parser.add_argument("--workspace", type=str, default="projects/workspace", 
                       help="Directory where the project will be built (default: projects/workspace)")
    parser.add_argument("--mock-run", action="store_true", help="Run in mock mode (no LLM)")
    parser.add_argument("--provider", type=str, default="openai", 
                       choices=["openai", "anthropic", "google"],
                       help="LLM provider (default: openai)")
    parser.add_argument("--model", type=str, help="Model name (e.g., gpt-4o, claude-3-5-sonnet-20241022)")
    
    args = parser.parse_args()
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    # Disable LangSmith tracing by default (unless explicitly enabled)
    import os
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
            model_name = default_config.worker_model.model_name if default_config.worker_model.provider == "openai" else "gpt-4o"
        elif args.provider == "anthropic":
            model_name = default_config.worker_model.model_name if default_config.worker_model.provider == "anthropic" else "claude-3-5-sonnet-20241022"
        else:  # google
            model_name = "gemini-1.5-pro"
    
    # Create config
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
        result = start_run(
            objective=args.objective,
            workspace=args.workspace,
            config=config
        )
        
        print(f"\n{'='*60}")
        print("RUN COMPLETE")
        print(f"{'='*60}")
        
        tasks = result.get('tasks', [])
        print(f"Total tasks: {len(tasks)}")
        for t in tasks:
            status_icon = "[OK]" if t.get('status') == 'complete' else "[X]"
            print(f"{status_icon} {t.get('id')}: {t.get('status')} - {t.get('description')}")
            
        completed = [t for t in tasks if t.get('status') == 'complete']
        print(f"\nTasks completed: {len(completed)}/{len(tasks)}")
        
        return 0
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
