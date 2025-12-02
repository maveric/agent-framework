"""
Kanban Test 9 - Director-led architecture with strict scope control
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from langgraph_definition import start_run
from config import OrchestratorConfig, ModelConfig

# Configuration
config = OrchestratorConfig(
    max_concurrent_workers=5,
    director_model=ModelConfig(
        provider="anthropic",
        model_name="claude-3-7-sonnet-20250219",
        temperature=0.3
    ),
    strategist_model=ModelConfig(
        provider="anthropic",
        model_name="claude-3-7-sonnet-20250219",
        temperature=0.3
    ),
    worker_model=ModelConfig(
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        temperature=0.3
    ),
    mock_mode=False
)

objective = """Build a Kanban board web application with drag-and-drop functionality.

Requirements:
- Three columns: To Do, In Progress, Done
- Ability to add new tasks
- Drag and drop tasks between columns
- Tasks should persist (use localStorage or simple JSON file)
- Clean, modern UI
- Works in modern browsers"""

workspace = "./agent-workspaces/kanban-test-9"

print("=" * 80)
print("KANBAN TEST 9")
print("=" * 80)
print(f"Objective: {objective[:100]}...")
print(f"Workspace: {workspace}")
print(f"Director Model: {config.director_model.model_name}")
print(f"Worker Model: {config.worker_model.model_name}")
print(f"Max Concurrent: {config.max_concurrent_workers}")
print("=" * 80)
print()

# Run orchestrator
result = start_run(
    objective=objective,
    workspace=workspace,
    config=config
)

print()
print("=" * 80)
print("RUN COMPLETE")
print("=" * 80)
print(f"Total tasks: {len(result.get('tasks', []))}")
print(f"Workspace: {workspace}")
print()

# Summary
tasks = result.get("tasks", [])
by_status = {}
for t in tasks:
    status = t.get("status", "unknown")
    by_status[status] = by_status.get(status, 0) + 1

print("Task Status Summary:")
for status, count in sorted(by_status.items()):
    print(f"  {status}: {count}")
