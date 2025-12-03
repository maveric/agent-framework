# Recursion Limit Fix

## Problem
When LLM hits recursion limit (150 steps), it gets "Sorry, need more steps" error and tries to work around it by creating wrapper scripts that call other scripts infinitely.

Result: Dozens of temp files like:
- cleanup.py → calls execute_cleanup.py
- execute_cleanup.py → calls final_cleanup.py  
- final_cleanup.py → calls ultimate_cleanup.py
- etc.

## Solutions

### Option 1: Increase Recursion Limit
**Pros**: Simple
**Cons**: Just delays the problem, costs more tokens

### Option 2: Detect Wrapper Script Pattern (RECOMMENDED)
Add detection in worker.py that fails the task if it sees:
- Multiple .py files created with "cleanup", "execute", "run", "final" in names
- subprocess.run() calling other .py files in the same directory
- More than N temp script files created

**Implementation**:
After each tool call, check if creating wrapper scripts. If detected, fail with clear message.

### Option 3: Better System Prompt
Add to worker prompt:
```
CRITICAL: If you hit recursion limit error:
- DO NOT create wrapper scripts to work around it
- DO NOT create scripts that call other scripts  
- Instead: Consolidate your work into ONE script
- Or: Report that task is too complex and needs to be broken down
```

## Recommendation
Implement Options 2 + 3:
1. Add system prompt warning
2. Add runtime detection to catch and fail the pattern

This prevents token waste and gives clear feedback that task needs decomposition.
