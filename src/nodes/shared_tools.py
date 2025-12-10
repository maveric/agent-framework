"""
Shared tools used by multiple worker profiles.
"""

from typing import List, Dict, Any


def create_subtasks(subtasks: List[Dict[str, Any]]) -> str:
    """
    Create COMMIT-LEVEL subtasks to be executed by other workers.

    IMPORTANT: Think in terms of GIT COMMITS, not components!
    Each task should represent ONE atomic, reviewable change.

    Args:
        subtasks: List of dicts, each containing:
            - title: str (concise, commit-message-style)
            - description: str (what changes, why, acceptance criteria)
            - phase: "build" | "test" (NOT separate - build includes inline tests)
            - component: str (optional, use feature name instead of "backend"/"frontend")
            - depends_on: List[str] (titles of tasks this depends on)
            - worker_profile: "code_worker" | "test_worker" (default based on phase)

    EXAMPLES OF GOOD TASKS:
    {
      "title": "Create tasks table in SQLite database",
      "description": "Set up database schema with id, title, status columns. Include migration script and verification query.",
      "phase": "build",
      "depends_on": []
    },
    {
      "title": "Implement GET /api/tasks endpoint",
      "description": "Create Flask route to return all tasks as JSON. Include unit test for happy path and empty state.",
      "phase": "build",
      "depends_on": ["Create tasks table in SQLite database"]
    },
    {
      "title": "Playwright test: Add and view task",
      "description": "E2E test that adds a task via UI and verifies it appears in correct column.",
      "phase": "test",
      "depends_on": ["Implement POST /api/tasks endpoint", "Add task creation UI component"]
    }

    Returns:
        Status message or error
    """
    # ENFORCE LIMITS TO PREVENT TASK EXPLOSION
    # Note: This limits each CALL to create_subtasks, not total tasks.
    # A planner can call this multiple times if needed for complex projects.
    MAX_SUBTASKS_PER_CALL = 15

    if len(subtasks) > MAX_SUBTASKS_PER_CALL:
        return f"ERROR: Too many subtasks ({len(subtasks)}). Maximum allowed is {MAX_SUBTASKS_PER_CALL}. Break into smaller logical groups or prioritize the most critical tasks."

    if len(subtasks) == 0:
        return "ERROR: No subtasks provided. You must create at least one subtask."
    
    # VALIDATE EACH SUBTASK BEFORE ACCEPTING
    # This gives the LLM immediate feedback to fix issues in the same conversation
    VALID_PHASES = ["plan", "build", "test"]
    errors = []
    
    for idx, subtask in enumerate(subtasks):
        st_num = idx + 1
        
        # Check if dict
        if not isinstance(subtask, dict):
            errors.append(f"Subtask #{st_num}: Must be a dictionary, got {type(subtask).__name__}")
            continue
        
        # Check required fields
        if "title" not in subtask or not subtask["title"]:
            errors.append(f"Subtask #{st_num}: Missing required field 'title'")
        
        if "description" not in subtask or not subtask["description"]:
            errors.append(f"Subtask #{st_num}: Missing required field 'description'")
        
        # Validate phase
        phase = subtask.get("phase", "build")
        if phase not in VALID_PHASES:
            errors.append(
                f"Subtask #{st_num} '{subtask.get('title', 'Untitled')}': Invalid phase '{phase}'. "
                f"Valid phases are: {VALID_PHASES}. "
                f"Use 'build' for frontend/backend/setup work, 'plan' for breaking down complex features, 'test' for E2E testing."
            )
    
    # If validation errors, return them immediately for LLM to fix
    if errors:
        error_msg = f"VALIDATION ERRORS ({len(errors)} issues found):\n" + "\n".join(f"  - {err}" for err in errors)
        error_msg += "\n\nPlease fix these errors and call create_subtasks again with valid task definitions."
        return error_msg

    return f"Created {len(subtasks)} subtasks. They will be added to the task graph by the Director."


def report_existing_implementation(file_path: str, implementation_summary: str, verification_details: str) -> str:
    """
    Report that a PREVIOUS task already implemented the requested feature.

    **CRITICAL RULE**: This tool is ONLY for pre-existing code you FOUND in the codebase.

    DO NOT use this tool if:
    - You just created or modified files in THIS session
    - You wrote ANY code to complete the task
    - You used write_file, append_file, or any file modification tools

    ONLY use this tool if:
    - You explored the codebase and found that a PREVIOUS task already did your work
    - The existing code fully satisfies your task requirements
    - You made ZERO modifications to any files

    If you created files, your work needs to be committed. Do NOT call this tool.

    Args:
        file_path: Path to the EXISTING file that already has the implementation
        implementation_summary: Brief description of what the existing code does
        verification_details: Explanation of why it meets YOUR task requirements

    Returns:
        Status message
    """
    return "Implementation reported successfully."
