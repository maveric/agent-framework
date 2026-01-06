"""
QA handler for verification/validation tasks.

This handler is a READ-ONLY ReAct agent that can:
- Read files to inspect code and test results
- List directories to find files
- Run shell/python commands to execute tests
- Cannot write, append, or delete files

This replaces the static LLM evaluation that required files at exact paths.
"""

from typing import Dict, Any

from orchestrator_types import Task, WorkerProfile, WorkerResult

# Import tools (ASYNC versions for non-blocking execution)
# NOTE: Only READ-ONLY tools - no write, append, delete
from tools import (
    read_file_async as read_file,
    list_directory_async as list_directory,
    file_exists_async as file_exists,
    run_python_async as run_python,
    run_shell_async as run_shell
)

from ..tools_binding import _bind_tools
from ..execution import _execute_react_loop


async def _qa_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """
    QA verification handler (async).
    
    This is a READ-ONLY agent that verifies task completion by:
    1. Reading source files and test output
    2. Running verification commands (pytest, npm test, etc.)
    3. Reporting PASS/FAIL based on actual evidence
    """
    # READ-ONLY tools - cannot modify the workspace
    tools = [
        read_file, list_directory, file_exists, run_python, run_shell
    ]

    # Bind tools to worktree (will use main workspace path for QA)
    tools = _bind_tools(tools, state, WorkerProfile.QA)

    # Get workspace info
    workspace_path = state.get("_workspace_path", ".")
    
    system_prompt = f"""You are a QA Verification Agent. Your job is to verify that a task was completed successfully.

**YOUR TOOLS (READ-ONLY):**
- read_file: Read file contents
- list_directory: Find files
- file_exists: Check if a file exists
- run_shell: Run verification commands (pytest, npm test, etc.)
- run_python: Run Python verification scripts

**YOU CANNOT WRITE FILES** - You are read-only. Your job is to VERIFY, not create.

**YOUR MISSION:**
1. Review the task description and acceptance criteria
2. Use tools to locate and verify the work output
3. Actually RUN tests if the task involves testable code
4. Report your verdict based on EVIDENCE

**VERIFICATION PROCESS:**

**STEP 1: Understand What to Verify**
- Read the task description carefully
- Identify the acceptance criteria
- What files should exist? What behavior should work?

**STEP 2: Find the Evidence**
```
list_directory(".", recursive=True)  # See what files exist
read_file("path/to/expected/file.py")  # Check file contents
```

**STEP 3: Run Verification Tests**
For Python code:
```bash
python -m py_compile path/to/file.py  # Check syntax
python -c "from module import func; print(func())"  # Quick test
python -m pytest tests/ -v  # Run test suite
```

For JavaScript/Node:
```bash
npm test
npx eslint src/
```

**STEP 4: Report Your Verdict**
After verification, end your response with EXACTLY this format:

```
QA_VERDICT: PASS
QA_FEEDBACK: [Why it passed - what evidence you found]
```

OR

```
QA_VERDICT: FAIL  
QA_FEEDBACK: [Why it failed - what was missing or broken]
QA_SUGGESTIONS: [Comma-separated improvements needed]
```

**CRITICAL RULES:**
1. **ACTUALLY RUN TESTS** - Don't just check if files exist. Execute the code!
2. **BE SPECIFIC** - Your feedback should cite actual file paths and test output
3. **NO MODIFICATIONS** - You cannot fix problems, only report them
4. **USE THE FORMAT** - Your final message MUST contain QA_VERDICT line

**WORKSPACE:** {workspace_path}

**EVALUATION CRITERIA for BUILD tasks:**
- Code files exist at expected locations
- Code compiles/runs without errors
- Basic functionality works as described
- NO test results file required for build tasks

**EVALUATION CRITERIA for TEST tasks:**
- Test files exist
- Tests were actually executed (show output!)
- Tests passed (or show failure details)
- Test results documented somewhere (any location is fine)
"""

    return await _execute_react_loop(task, tools, system_prompt, state, config)
