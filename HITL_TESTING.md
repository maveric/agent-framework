# HITL Testing Guide
## Quick Test Without Burning Tokens

### Option 1: Direct API Test (Fastest)

Test the interrupt detection and resolution endpoints directly:

```bash
# 1. Create a test interrupt state manually
# Edit orchestrator.db and add an interrupt to a test run

# 2. Test GET /interrupts endpoint
curl http://localhost:8085/api/runs/{run_id}/interrupts

# Expected response:
# {"interrupted": true, "data": {...task_context...}}

# 3. Test POST /resolve endpoint with retry
curl -X POST http://localhost:8085/api/runs/{run_id}/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "action": "retry",
    "modified_description": "Updated task description"
  }'

# Expected: {"status": "resuming", "action": "retry"}
```

### Option 2: Simulation Script (Recommended)

Use the test script to create pre-failed scenarios:

```bash
# Run the simulation script
python test_hitl_simulation.py

# Choose Option 1 to create pre-failed tasks in DB
# This creates tasks with retry_count=4 that will trigger interrupt
```

### Option 3: Mock Worker (Full Flow Test)

Creates a run with an impossible objective that will fail quickly:

```bash
# Start the mock worker
python test_hitl_mock_worker.py --workspace test-hitl-ws

# This will:
# 1. Create an impossible task (import nonexistent_module)
# 2. Let it fail 4 times (fast, no token waste)
# 3. Trigger interrupt() on 5th attempt
# 4. Pause for human intervention
```

### Option 4: Manual Task Injection

Inject a failed task via Python:

```python
from orchestrator_types import Task, TaskStatus, AAR
from datetime import datetime
import uuid

# Create a task that's already failed 4 times
failed_task = Task(
    id=f"task_{uuid.uuid4().hex[:8]}",
    component="Test Component",
    phase="build",
    status="failed",
    retry_count=4,  # Will trigger HITL on next director run
    aar=AAR(
        summary="Simulated failure for HITL testing",
        approach="Attempted to create test component",
        challenges=["Simulated failure", "Test scenario"],
        decisions_made=["Created for HITL testing"],
        files_modified=[],
        time_spent_estimate="N/A"
    ),
    description="Test task that will trigger human intervention",
    acceptance_criteria=["Test criterion"],
    assigned_worker_profile="code_worker",
    depends_on=[],
    created_at=datetime.now(),
    updated_at=datetime.now()
)

# Add to existing run's state via update_state()
```

### Testing the UI

1. Open dashboard: `http://localhost:3000`
2. Navigate to the test run
3. You should see the `InterruptModal` appear automatically
4. Test each resolution action:
   - **Retry**: Modify description/criteria
   - **Spawn New Task**: Create replacement task
   - **Abandon**: Mark as abandoned

### Verification Checklist

- [ ] Modal appears when task exceeds max retries
- [ ] Failure reason is displayed
- [ ] Can edit task description
- [ ] Can edit acceptance criteria
- [ ] "Retry" button works
- [ ] "Spawn New Task" form appears
- [ ] Component/Phase/Worker selectors work
- [ ] "Abandon" button works
- [ ] Modal closes after resolution
- [ ] Run resumes after resolution

### Debug Tips

**If modal doesn't appear:**
1. Check browser console for polling errors
2. Verify server is running: `http://localhost:8085/health`
3. Check interrupt endpoint manually:
   ```bash
   curl http://localhost:8085/api/runs/{run_id}/interrupts
   ```
4. Look for "requesting human intervention" in server logs

**If resolution doesn't work:**
1. Check network tab for POST request to `/resolve`
2. Verify request payload matches `HumanResolution` model
3. Check server logs for Command execution errors
4. Ensure run is actually paused (not already completed)
