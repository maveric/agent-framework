# Chunked Agent Execution with Guardian Checkpoints

## Overview
Instead of running agents with a single large recursion limit (e.g., 150 steps), split execution into smaller chunks with periodic oversight checkpoints. This enables mid-execution intervention, loop detection, and guardian oversight.

## Core Concept

### Current Pattern (Single Invoke)
```python
# Agent runs to completion or hits limit
result = agent.invoke(
    {"messages": initial_messages}, 
    config={"recursion_limit": 150}
)
# No oversight until complete
```

### Proposed Pattern (Chunked with Checkpoints)
```python
total_steps = 0
messages = initial_messages
CHUNK_SIZE = 30      # Guardian checks every 30 steps
MAX_TOTAL_STEPS = 150

while total_steps < MAX_TOTAL_STEPS:
    # Run one chunk
    result = agent.invoke(
        {"messages": messages}, 
        config={"recursion_limit": CHUNK_SIZE}
    )
    
    # Count steps taken (tool calls)
    chunk_steps = len([
        m for m in result["messages"] 
        if isinstance(m, AIMessage) and m.tool_calls
    ])
    total_steps += chunk_steps
    
    # Update conversation with chunk results
    messages = result["messages"]
    
    # === CHECKPOINT: Guardian Oversight ===
    guardian_response = check_with_guardian(messages, task_context)
    
    if guardian_response.intervention_needed:
        # Inject guardian message into conversation
        messages.append(SystemMessage(
            content=f"🛡️ GUARDIAN: {guardian_response.message}"
        ))
        
        if guardian_response.should_terminate:
            break
    
    # Check if task complete
    last_msg = messages[-1]
    if is_task_complete(last_msg):
        break

# Return final result
return WorkerResult(messages=messages, ...)
```

## Key Insight: Agent is Stateless

The React agent doesn't remember anything between `invoke()` calls. All state lives in the **messages list**. This means:

- ✅ We can pause execution after N steps
- ✅ Inspect the conversation transcript
- ✅ Insert our own messages (guardian feedback)
- ✅ Resume execution seamlessly
- ✅ To the agent, injected messages appear as part of original conversation

## Use Cases

### 1. Loop Detection (Immediate Need)
Detect when agent calls the same tool 10+ times in a row:

```python
# After each chunk
loop_info = detect_loop(messages)
if loop_info.detected:
    messages.append(SystemMessage(
        f"⚠️ LOOP DETECTED: You called '{loop_info.tool}' "
        f"{loop_info.count} times. This suggests wrapper scripts. "
        f"Consolidate into ONE script or break down the task."
    ))
    # Agent gets immediate feedback and can course-correct
```

### 2. Guardian Oversight (Future)
Periodic checks against scope, design spec, and budget:

```python
guardian_check = guardian.evaluate(
    messages=messages,
    task=task,
    spec=design_spec,
    budget_remaining=token_budget
)

if guardian_check.scope_violation:
    messages.append(SystemMessage(
        f"🛡️ SCOPE: You're implementing {guardian_check.violation}. "
        f"This is NOT in design_spec.md. Return to spec requirements."
    ))

if guardian_check.token_warning:
    messages.append(SystemMessage(
        f"🛡️ BUDGET: {guardian_check.tokens_used}/{guardian_check.budget} "
        f"tokens used. Wrap up your current work."
    ))
```

### 3. Progress Tracking
Monitor that agent is making meaningful progress:

```python
progress = analyze_progress(messages)
if progress.stuck_count > 3:
    messages.append(SystemMessage(
        "🛡️ PROGRESS: You seem stuck. Consider breaking this "
        "into smaller subtasks or requesting help."
    ))
```

## Implementation Details

### Counting Steps
A "step" is typically a tool call:

```python
def count_steps(messages):
    return sum(
        len(msg.tool_calls) 
        for msg in messages 
        if isinstance(msg, AIMessage) and msg.tool_calls
    )
```

### Chunk Size Selection
- **Too small (10)**: Frequent interruptions, overhead
- **Too large (100)**: Defeats purpose, less responsive
- **Recommended (30)**: Good balance between progress and oversight

### Guardian Interface
```python
class GuardianResponse:
    intervention_needed: bool
    message: str
    should_terminate: bool
    severity: str  # "info", "warning", "critical"

def check_with_guardian(
    messages: List[BaseMessage],
    task: Task,
    spec: Dict,
    budget: TokenBudget
) -> GuardianResponse:
    """
    Evaluate current agent conversation for:
    - Scope violations
    - Token budget
    - Loop patterns
    - Progress stalls
    - Code quality issues
    """
    pass
```

## Benefits

1. **Early Detection**: Catch issues before hitting recursion limit
2. **Course Correction**: Agent can adjust based on feedback
3. **Token Savings**: Stop runaway processes early
4. **Better UX**: User sees guardian interventions in real-time
5. **Auditable**: Guardian checks logged at each checkpoint

## Migration Path

### Phase 1: Loop Detection Only
- Implement chunked execution for loop detection
- Guardian checkpoint = simple loop check
- Validate pattern works

### Phase 2: Basic Guardian
- Add scope checking
- Add token budget warnings
- Keep interventions simple

### Phase 3: Full Guardian
- LLM-powered oversight
- Design spec validation
- Code quality checks
- Budget management

## Open Questions

1. **Chunk size tuning**: Should it vary by task type (plan=50, code=30, test=40)?
2. **Guardian persistence**: Should guardian state persist across chunks?
3. **Intervention severity**: When to warn vs. when to terminate?
4. **User visibility**: Should guardian messages appear in UI?

## Related
- See `spec/guardian.md` for full guardian specification
- Loop detection implementation (when added)
- Token budget tracking
