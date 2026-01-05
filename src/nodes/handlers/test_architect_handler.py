"""
Test Architect Handler (TDD)
============================
Writes failing tests FROM interface specifications BEFORE implementation.

This is the "Red" phase of TDD:
1. Read interface contracts (api_spec.yaml, models.py)
2. Write tests that exercise those contracts
3. Verify tests FAIL (because implementation doesn't exist yet)
4. Mark task as ready for Code Worker to make tests pass
"""

from typing import Dict, Any
import platform
import logging

from orchestrator_types import Task, WorkerProfile, WorkerResult, AAR

# Import tools (ASYNC versions for non-blocking execution)
from tools import (
    read_file_async as read_file,
    write_file_async as write_file,
    list_directory_async as list_directory,
    run_python_async as run_python,
    run_shell_async as run_shell,
    file_exists_async as file_exists
)

from ..tools_binding import _bind_tools
from ..shared_tools import create_subtasks
from ..execution import _execute_react_loop

logger = logging.getLogger(__name__)

PLATFORM = f"OS - {platform.system()}, Release: {platform.release()}"


async def _test_architect_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """
    TDD Test Architect - writes failing tests from interface specs.

    This handler is fundamentally different from the legacy test_handler:
    - Reads interface specs, NOT implementation code
    - Writes tests that MUST FAIL initially
    - Verifies RED state before passing to Code Worker
    """
    tools = [read_file, write_file, list_directory, run_python, run_shell, file_exists, create_subtasks]
    tools = _bind_tools(tools, state, WorkerProfile.TEST_ARCHITECT)

    # Shared venv path at workspace root (not in worktree)
    is_windows = platform.system() == 'Windows'
    workspace_path = state.get("_workspace_path", ".")
    if is_windows:
        venv_python = f"{workspace_path}\\.venv\\Scripts\\python.exe"
        venv_pip = f"{workspace_path}\\.venv\\Scripts\\pip.exe"
    else:
        venv_python = f"{workspace_path}/.venv/bin/python"
        venv_pip = f"{workspace_path}/.venv/bin/pip"

    # Component for file naming
    task_filename = task.component if task.component else task.id

    # Get interface spec path from task if available
    interface_spec_path = getattr(task, 'interface_spec_path', None) or 'interfaces/api_spec.yaml'

    system_prompt = f"""You are a TDD Test Architect. Your job is to write FAILING tests from interface specifications.

## 🔴 THIS IS THE "RED" PHASE OF TDD 🔴

You write tests BEFORE any implementation exists. Your tests MUST FAIL when run.
If tests pass, something is wrong (either tests are trivial or code already exists).

---

## YOUR MISSION

1. **READ THE INTERFACE CONTRACTS**:
   - `interfaces/api_spec.yaml` - OpenAPI specification with endpoints
   - `interfaces/models.py` - Pydantic model definitions
   - `interfaces/types.ts` - TypeScript types (if frontend)
   - `design_spec.md` - High-level architecture reference

2. **WRITE TESTS** that exercise these contracts:
   - API endpoints: Test all HTTP methods, request/response shapes
   - Data models: Test validation, serialization, edge cases
   - Use semantic locators for UI tests (see below)

3. **VERIFY RED STATE** (tests fail):
   - Run the tests
   - Confirm they FAIL with appropriate errors (e.g., ImportError, 404, ConnectionRefused)
   - This proves the tests are meaningful and await implementation

4. **OUTPUT REQUIREMENTS**:
   - Write test files to the project (e.g., `tests/test_api.py`, `tests/test_models.py`)
   - Create a RED verification report at `agents-work/test-specs/test-spec-{task_filename}.md`

---

## CRITICAL: RED VERIFICATION REPORT

**BEFORE YOU FINISH, CREATE THIS FILE:**

    File path: `agents-work/test-specs/test-spec-{task_filename}.md`

**YOUR TASK WILL FAIL IF THIS FILE DOES NOT EXIST!**

Required content:
```markdown
# TDD Test Specification: {task_filename}

## Interface Contracts Referenced
- interfaces/api_spec.yaml: [endpoints covered]
- interfaces/models.py: [models covered]

## Test Files Created
- tests/test_<component>.py: [number of test cases]

## RED Verification (Tests Must Fail)
Command: `{venv_python} -m pytest tests/test_<component>.py -v`

Output:
```
[Paste actual pytest output showing FAILURES]
```

### Failure Analysis
- Expected failures: [describe why each test fails - missing module, 404, etc.]
- Unexpected passes: [NONE - if any tests pass, investigate!]

## Ready for Code Worker
✅ Tests are written and verified to fail
✅ Interface contracts are fully covered
✅ Code Worker can now implement to make tests pass
```

---

## TEST WRITING RULES

### API Tests
```python
import pytest
import requests

BASE_URL = "http://localhost:8000"  # Will fail until server exists

def test_create_user():
    \"\"\"POST /api/users - from api_spec.yaml\"\"\"
    response = requests.post(f"{{BASE_URL}}/api/users", json={{
        "name": "Test User",
        "email": "test@example.com"
    }})
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["name"] == "Test User"

def test_get_users():
    \"\"\"GET /api/users - from api_spec.yaml\"\"\"
    response = requests.get(f"{{BASE_URL}}/api/users")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

### Model Tests
```python
import pytest
from pydantic import ValidationError

def test_user_model_validation():
    \"\"\"User model from interfaces/models.py\"\"\"
    # This will fail with ImportError until models are implemented
    from models import User

    user = User(id=1, name="Test", email="test@example.com")
    assert user.id == 1

    with pytest.raises(ValidationError):
        User(id="not-an-int", name="", email="invalid")
```

### UI Tests (Use Semantic Locators!)
```python
# GOOD - Semantic locators (resilient to CSS changes)
page.get_by_role("button", name="Submit")
page.get_by_label("Email")
page.get_by_text("Welcome")
page.get_by_test_id("user-card")  # data-testid attribute

# BAD - CSS selectors (brittle)
page.locator(".btn-primary")  # Avoid!
page.locator("#submit-btn")   # Avoid!
```

---

## ANTI-PATTERNS (FORBIDDEN)

❌ **NO TRIVIAL TESTS**:
```python
def test_true():
    assert True  # FORBIDDEN - proves nothing
```

❌ **NO MOCKING THE THING BEING TESTED**:
```python
def test_api(mocker):
    mocker.patch('api.create_user', return_value={{"id": 1}})
    # FORBIDDEN - you're testing the mock, not the API
```

❌ **NO TESTS THAT PASS BEFORE IMPLEMENTATION**:
If a test passes, either:
1. The test is trivial (fix it)
2. Implementation already exists (skip that test)
3. Something is wrong (investigate)

---

## DEPENDENCY ISOLATION

**Python**: Use shared venv at workspace root:
- Run tests: `{venv_python} -m pytest tests/ -v`
- Install deps: `{venv_pip} install pytest requests`
- **NEVER** create a new venv

**Node.js**: Use `npm test` or `npx jest`

Platform: {PLATFORM}
{'- Windows PowerShell: Use semicolons (;) NOT double-ampersand (&&)' if platform.system() == 'Windows' else '- Unix shell: Use && or ; for chaining'}

---

## WORKFLOW

1. **Read** `interfaces/api_spec.yaml` and `interfaces/models.py`
2. **Create** test directory if needed: `tests/`
3. **Write** test files based on interface contracts
4. **Run** tests to verify they FAIL
5. **Create** the RED verification report
6. **Complete** task - Code Worker will make tests pass

Remember: Your tests are the CONTRACT. The Code Worker's only job is to make your tests pass.
"""

    # INJECT PHOENIX RETRY CONTEXT if this is a retry attempt
    from ..utils import get_phoenix_retry_context
    phoenix_context = get_phoenix_retry_context(task)
    if phoenix_context:
        system_prompt = f"{phoenix_context}\n\n{system_prompt}"

    result = await _execute_react_loop(task, tools, system_prompt, state, config)

    # Post-execution: Verify RED state was documented
    if result and result.status == "complete":
        # Check if the test spec file was created
        test_spec_path = f"agents-work/test-specs/test-spec-{task_filename}.md"
        logger.info(f"Test Architect completed. Expected test spec at: {test_spec_path}")

        # The is_red_verified flag should ideally be set based on actual verification
        # For now, we trust the agent followed instructions
        # In a future enhancement, we could parse the report and validate

    return result
