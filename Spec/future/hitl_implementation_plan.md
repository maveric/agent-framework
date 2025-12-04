# Human-in-the-Loop Implementation Plan

## Executive Summary

When tasks exceed max retries (currently causing ABANDONED status), enable human intervention to:
1. Review failure reasons
2. Modify task description/criteria
3. Approve retry or cancel task
4. Unblock stuck workflows

**Estimated Effort**: 2-3 days (Medium complexity)

---

## Current State Analysis

### Existing Infrastructure ✅
- **Server**: FastAPI with WebSocket support ([`server.py`](file:///f:/coding/agent-framework/src/server.py))
- **Database**: SQLite checkpointer (already configured)
- **UI**: React dashboard with real-time updates
- **Models**: `HumanResolution` already defined (lines 54-59)

### Gap: No LangGraph Interrupt Configuration
- Graph is compiled WITHOUT `interrupt_before` or `interrupt_after`
- No nodes are set up to call `interrupt()` function
- No resume mechanism in place

---

## LangGraph HITL Mechanisms

### Option 1: `interrupt_after` (Simple but Inefficient)

**When to use**: After Phoenix marks task as ABANDONED, pause for human review

**Implementation**:
```python
# langgraph_definition.py
return graph.compile(
    checkpointer=checkpointer,
    interrupt_after=["director"]  # Pause after director processes failures
)
```

**Pros**:
- Simple configuration
- Automatic state persistence
- Works with existing flow

**Cons**:
- Fires on EVERY director run (need conditional logic)

---

### Option 2: Dynamic `interrupt()` Call (Recommended) ✅

**When to use**: Only when tasks hit ABANDONED status

**Implementation**:
```python
# director.py - inside Phoenix recovery
from langgraph.types import interrupt

if retry_count >= MAX_RETRIES:
    # Pause and request human intervention
    resolution = interrupt({
        "type": "task_exceeded_retries",
        "task_id": task.id,
        "task": task_to_dict(task),
        "failure_reason": task.aar.summary if task.aar else "Unknown",
        "retry_count": retry_count
    })
    
    # Process human response (after resume)
    if resolution["action"] == "retry":
        task.description = resolution.get("modified_description", task.description)
        task.retry_count = 0  # Reset
        task.status = TaskStatus.PLANNED
    elif resolution["action"] == "abandon":
        task.status = TaskStatus.ABANDONED
```

**Pros**:
- Fires only when needed
- Granular control
- Passes context to UI

**Cons**:
- Requires conditional logic in node

---

## Recommended Approach: Dynamic `interrupt()`

### Why?
1. **Selective**: Only pauses for ABANDONED tasks, not all director runs
2. **Contextual**: Passes task details directly to UI
3. **Flexible**: Can expand to other interrupt points later

---

## Implementation Plan

### Phase 1: Backend - Director Node Changes

**File**: `src/nodes/director.py`

**Change 1**: Import interrupt and uuid
```python
from langgraph.types import interrupt
import uuid
```

**Change 2**: Modify Phoenix recovery (replace lines 195-205)
```python
else:
    print(f"Phoenix: Task {task.id} exceeded max retries, requesting human intervention", flush=True)
    
    # Prepare interrupt payload
    interrupt_data = {
        "type": "task_exceeded_retries",
        "task_id": task.id,
        "task_description": task.description,
        "component": task.component,
        "phase": task.phase.value,
        "retry_count": retry_count,
        "failure_reason": task.aar.summary if task.aar else "No details available",
        "acceptance_criteria": task.acceptance_criteria,
        "files_modified": task.aar.files_modified if task.aar else [],
        "assigned_worker_profile": task.assigned_worker_profile.value,
        "depends_on": task.depends_on
    }
    
    # Pause and wait for human resolution
    resolution = interrupt(interrupt_data)
    
    # Process human decision
    if resolution and resolution.get("action") == "retry":
        print(f"  Human approved retry for task {task.id}", flush=True)
        task.retry_count = 0  # Reset retry counter
        task.status = TaskStatus.PLANNED
        
        # Apply modifications if provided
        if resolution.get("modified_description"):
            task.description = resolution["modified_description"]
        if resolution.get("modified_criteria"):
            task.acceptance_criteria = resolution["modified_criteria"]
        
        task.updated_at = datetime.now()
        updates.append(task_to_dict(task))
        
    elif resolution and resolution.get("action") == "spawn_new_task":
        print(f"  Human requested new task to replace {task.id}", flush=True)
        
        # Mark original as abandoned
        task.status = TaskStatus.ABANDONED
        task.updated_at = datetime.now()
        updates.append(task_to_dict(task))
        
        # Create new task from resolution data
        new_task_id = f"task_{uuid.uuid4().hex[:8]}"
        new_task = Task(
            id=new_task_id,
            component=resolution.get("new_component", task.component),
            phase=TaskPhase(resolution.get("new_phase", task.phase.value)),
            status=TaskStatus.PLANNED,
            assigned_worker_profile=WorkerProfile(resolution.get("new_worker_profile", task.assigned_worker_profile.value)),
            description=resolution["new_description"],
            acceptance_criteria=resolution.get("new_criteria", task.acceptance_criteria),
            depends_on=resolution.get("new_dependencies", []),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        updates.append(task_to_dict(new_task))
        
        # Trigger replan to reorganize dependencies
        # This will be handled by returning replan_requested in the result
        continue
        
    elif resolution and resolution.get("action") == "abandon":
        print(f"  Human abandoned task {task.id}", flush=True)
        task.status = TaskStatus.ABANDONED
        task.updated_at = datetime.now()
        updates.append(task_to_dict(task))
        continue
        
    else:
        # Default: abandon if no valid response
        task.status = TaskStatus.ABANDONED
        updates.append(task_to_dict(task))
        continue
```

---

### Phase 2: Backend - Server API Endpoints

**File**: `src/server.py`

**New Endpoint 1**: Get Interrupts
```python
@app.get("/api/runs/{run_id}/interrupts")
async def get_interrupts(run_id: str):
    """Check if run is paused waiting for human input."""
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    
    try:
        orchestrator = get_orchestrator_graph()
        thread_id = runs_index[run_id]["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}
        
        # Get current state snapshot
        state_snapshot = global_checkpointer.get(config)
        
        if state_snapshot:
            # Check for __interrupt__ field
            interrupts = state_snapshot.get("tasks", {}).get("__interrupt__")
            if interrupts:
                return {
                    "interrupted": True,
                    "data": interrupts[-1]  # Most recent interrupt
                }
        
        return {"interrupted": False}
        
    except Exception as e:
        logger.error(f"Error checking interrupts: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**New Endpoint 2**: Resume with Human Input
```python
from langgraph.types import Command

@app.post("/api/runs/{run_id}/resolve")
async def resolve_interrupt(run_id: str, resolution: HumanResolution):
    """Resume execution with human decision."""
    if run_id not in runs_index:
        raise HTTPException(status_code=404, detail="Run not found")
    
    try:
        orchestrator = get_orchestrator_graph()
        thread_id = runs_index[run_id]["thread_id"]
        config = {"configurable": {"thread_id": thread_id}}
        
        # Resume with Command
        result = orchestrator.invoke(
            Command(resume=resolution.dict()),
            config=config
        )
        
        logger.info(f"Resumed run {run_id} with action: {resolution.action}")
        return {"status": "resumed", "action": resolution.action}
        
    except Exception as e:
        logger.error(f"Error resuming run: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

---

### Phase 3: Frontend - UI Components

**File**: `orchestrator-dashboard/src/components/InterruptModal.tsx` (NEW)

```tsx
interface InterruptData {
  task_id: string;
  task_description: string;
  failure_reason: string;
  retry_count: number;
  acceptance_criteria: string[];
  component: string;
  phase: string;
  assigned_worker_profile: string;
  depends_on: string[];
}

export function InterruptModal({ runId, interruptData, onResolve }) {
  const [action, setAction] = useState<'retry' | 'abandon' | 'spawn_new_task'>('retry');
  const [modifiedDescription, setModifiedDescription] = useState(interruptData.task_description);
  const [modifiedCriteria, setModifiedCriteria] = useState(interruptData.acceptance_criteria);
  
  // Fields for new task spawning
  const [newDescription, setNewDescription] = useState(interruptData.task_description);
  const [newComponent, setNewComponent] = useState(interruptData.component);
  const [newPhase, setNewPhase] = useState(interruptData.phase);
  const [newWorkerProfile, setNewWorkerProfile] = useState(interruptData.assigned_worker_profile);
  const [newCriteria, setNewCriteria] = useState(interruptData.acceptance_criteria);
  const [newDependencies, setNewDependencies] = useState(interruptData.depends_on);
  
  const handleSubmit = async () => {
    let resolution;
    
    if (action === 'retry') {
      resolution = {
        action: 'retry',
        modified_description: modifiedDescription !== interruptData.task_description ? modifiedDescription : null,
        modified_criteria: modifiedCriteria !== interruptData.acceptance_criteria ? modifiedCriteria : null
      };
    } else if (action === 'spawn_new_task') {
      resolution = {
        action: 'spawn_new_task',
        new_description: newDescription,
        new_component: newComponent,
        new_phase: newPhase,
        new_worker_profile: newWorkerProfile,
        new_criteria: newCriteria,
        new_dependencies: newDependencies
      };
    } else {
      resolution = { action: 'abandon' };
    }
    
    await fetch(`/api/runs/${runId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(resolution)
    });
    
    onResolve();
  };
  
  return (
    <Modal title="Task Requires Human Review" size="large">
      <div className="space-y-4">
        <Alert variant="warning">
          Task {interruptData.task_id} exceeded max retries ({interruptData.retry_count})
        </Alert>
        
        <div>
          <h4>Failure Reason:</h4>
          <pre className="bg-gray-100 p-2 rounded">{interruptData.failure_reason}</pre>
        </div>
        
        <div className="border-t pt-4">
          <label className="flex items-center gap-2 mb-2">
            <input 
              type="radio" 
              checked={action === 'retry'}
              onChange={() => setAction('retry')}
            />
            <strong>Retry Task (with modifications)</strong>
          </label>
          
          {action === 'retry' && (
            <div className="ml-6 space-y-2">
              <div>
                <label>Task Description</label>
                <textarea 
                  value={modifiedDescription}
                  onChange={(e) => setModifiedDescription(e.target.value)}
                  rows={4}
                  className="w-full"
                />
              </div>
              
              <div>
                <label>Acceptance Criteria</label>
                {modifiedCriteria.map((criterion, i) => (
                  <input 
                    key={i}
                    value={criterion}
                    onChange={(e) => {
                      const newCriteria = [...modifiedCriteria];
                      newCriteria[i] = e.target.value;
                      setModifiedCriteria(newCriteria);
                    }}
                    className="w-full mb-1"
                  />
                ))}
              </div>
            </div>
          )}
        </div>
        
        <div className="border-t pt-4">
          <label className="flex items-center gap-2 mb-2">
            <input 
              type="radio" 
              checked={action === 'spawn_new_task'}
              onChange={() => setAction('spawn_new_task')}
            />
            <strong>Create New Task (replaces failed task)</strong>
          </label>
          
          {action === 'spawn_new_task' && (
            <div className="ml-6 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label>Component</label>
                  <input 
                    value={newComponent}
                    onChange={(e) => setNewComponent(e.target.value)}
                  />
                </div>
                <div>
                  <label>Phase</label>
                  <select value={newPhase} onChange={(e) => setNewPhase(e.target.value)}>
                    <option value="plan">Plan</option>
                    <option value="build">Build</option>
                    <option value="test">Test</option>
                  </select>
                </div>
              </div>
              
              <div>
                <label>Worker Profile</label>
                <select value={newWorkerProfile} onChange={(e) => setNewWorkerProfile(e.target.value)}>
                  <option value="planner_worker">Planner</option>
                  <option value="code_worker">Coder</option>
                  <option value="test_worker">Tester</option>
                </select>
              </div>
              
              <div>
                <label>Description</label>
                <textarea 
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  rows={4}
                />
              </div>
              
              <div>
                <label>Acceptance Criteria</label>
                {newCriteria.map((criterion, i) => (
                  <input 
                    key={i}
                    value={criterion}
                    onChange={(e) => {
                      const updated = [...newCriteria];
                      updated[i] = e.target.value;
                      setNewCriteria(updated);
                    }}
                    className="w-full mb-1"
                  />
                ))}
              </div>
            </div>
          )}
        </div>
        
        <div className="border-t pt-4">
          <label className="flex items-center gap-2">
            <input 
              type="radio" 
              checked={action === 'abandon'}
              onChange={() => setAction('abandon')}
            />
            <strong>Abandon Task</strong>
          </label>
        </div>
        
        <div className="flex gap-2 justify-end mt-4">
          <button onClick={handleSubmit} className="btn-primary">
            Submit
          </button>
        </div>
      </div>
    </Modal>
  );
}
```

**Update**: `RunDetailPage.tsx`
```tsx
// Poll for interrupts
useEffect(() => {
  const checkInterrupts = async () => {
    const res = await fetch(`/api/runs/${runId}/interrupts`);
    const data = await res.json();
    if (data.interrupted) {
      setInterruptData(data.data);
      setShowInterruptModal(true);
    }
  };
  
  const interval = setInterval(checkInterrupts, 2000);
  return () => clearInterval(interval);
}, [runId]);
```

---

### Phase 4: Server Model Update

**File**: `src/server.py`

**Update HumanResolution model** (lines 54-59):
```python
class HumanResolution(BaseModel):
    action: str  # 'retry', 'abandon', or 'spawn_new_task'
    
    # For 'retry' action
    modified_description: Optional[str] = None
    modified_criteria: Optional[List[str]] = None
    
    # For 'spawn_new_task' action
    new_description: Optional[str] = None
    new_component: Optional[str] = None
    new_phase: Optional[str] = None
    new_worker_profile: Optional[str] = None
    new_criteria: Optional[List[str]] = None
    new_dependencies: Optional[List[str]] = None
```

---

## Workflow Diagram

```
Task Fails → Director.Phoenix → Exceeds Max Retries
                                      ↓
                                interrupt(data)
                                      ↓
                                Graph saves state
                                      ↓
                                Execution pauses
                                      ↓
UI polls /interrupts ← Server ← Checkpointer
                                      ↓
                              Shows InterruptModal
                                      ↓
                          Human modifies + clicks Retry
                                      ↓
UI → POST /resolve → Server → invoke(Command(resume=...))
                                      ↓
                           Director resumes, processes
                                      ↓
                          Resets retry_count, continues
```

---

## Estimated Effort Breakdown

| Phase | Task | Effort | Risk |
|-------|------|--------|------|
| 1 | Director node changes | 2 hours | Low |
| 2 | Server API endpoints | 3 hours | Medium |
| 3 | Frontend UI components | 4 hours | Medium |
| 4 | Integration testing | 2 hours | Low |
| 5 | Documentation | 1 hour | Low |
| **Total** | | **12 hours** | **Medium** |

---

## Risks & Mitigation

### Risk 1: Interrupt Fires Too Often
**Mitigation**: Use dynamic `interrupt()` only in ABANDONED case, not static `interrupt_after`

### Risk 2: State Corruption on Resume
**Mitigation**: LangGraph handles checkpointing automatically; validate resolution before applying

### Risk 3: UI Polling Delay
**Mitigation**: Use WebSocket broadcast when interrupt detected (enhance existing manager)

---

## Future Enhancements

1. **Multiple Interrupt Types**: Pause for QA failures, plan reviews, etc.
2. **Approval Workflow**: Route to specific users/teams
3. **Audit Trail**: Log all human resolutions
4. **Batch Resolution**: Handle multiple paused tasks at once

---

## Decision: Proceed?

✅ **Low-hanging fruit**: Leverage existing infrastructure  
✅ **High value**: Unblock stuck workflows without manual code changes  
✅ **Scalable**: Foundation for more HITL patterns  

**Recommendation**: Implement Phases 1-2 first (backend only), test with API calls, then add UI.
