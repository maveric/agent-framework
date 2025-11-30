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

from langgraph_definition import create_orchestrator, start_run
from config import OrchestratorConfig


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Agent Orchestrator")
    parser.add_argument("--objective", type=str, help="What to build")
    parser.add_argument("--mock-run", action="store_true", help="Run with mock objective")
    args = parser.parse_args()
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    # Determine objective
    if args.mock_run:
        objective = "Create a simple hello world Python script"
    elif args.objective:
        objective = args.objective
    else:
        print("Error: Must provide --objective or --mock-run")
        sys.exit(1)
    
    print(f"\n{'='*60}")
    print(f"AGENT ORCHESTRATOR")
    print(f"{'='*60}")
    print(f"Objective: {objective}\n")
    
    # Create config
    config = OrchestratorConfig()
    if args.mock_run:
        config.mock_mode = True
    
    # Run orchestrator
    try:
        result = start_run(objective, config=config)
        
        print(f"\n{'='*60}")
        print("RUN COMPLETE")
        print(f"{'='*60}")
        
        tasks = result.get('tasks', [])
        print(f"Total tasks: {len(tasks)}")
        for t in tasks:
            print(f"- {t.get('id')}: {t.get('status')} ({t.get('description')})")
            
        completed = [t for t in tasks if t.get('status') == 'complete']
        print(f"Tasks completed: {len(completed)}")
        
        return 0
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
