"""
QA Agent for strategist verification.

A ReAct-style agent that can verify agent claims by reading files,
running tests, and checking acceptance criteria.
"""

import logging
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from llm_client import get_llm
from config import OrchestratorConfig

from .qa_tools import create_qa_tools

logger = logging.getLogger(__name__)

# Maximum tool calls to prevent runaway
MAX_TOOL_CALLS = 5


async def run_qa_agent(
    task: Dict[str, Any],
    aar_summary: str,
    acceptance_criteria: List[str],
    files_modified: List[str],
    worktree_path: str,
    workspace_path: str,
    test_output: Optional[str] = None,
    already_implemented_claim: Optional[str] = None,
    config: Any = None
) -> Dict[str, Any]:
    """
    ReAct-style QA agent that verifies task completion by reading files.
    
    Args:
        task: The task being evaluated
        aar_summary: Agent's summary of work done
        acceptance_criteria: List of acceptance criteria to check
        files_modified: List of files the agent claims to have modified
        worktree_path: Path to the task's worktree
        workspace_path: Main workspace path
        test_output: Output from test execution, if any
        already_implemented_claim: If agent claims work was already done
        config: Orchestrator config
        
    Returns:
        Dict with keys: passed (bool), feedback (str), focus (str)
    """
    logger.info(f"  [QA Agent] Starting verification for task {task.get('id', 'unknown')}")
    
    # Get config
    if not config:
        config = OrchestratorConfig()
    
    # Create tools bound to worktree
    tools = create_qa_tools(worktree_path, workspace_path)
    
    # Get LLM
    llm = get_llm(config.strategist_model)
    
    # Build criteria text
    criteria_text = "\n".join(f"- {c}" for c in acceptance_criteria) if acceptance_criteria else "No specific criteria defined"
    
    # Build files section
    files_section = ""
    if files_modified:
        files_section = f"\n\nFILES AGENT CLAIMS TO HAVE MODIFIED:\n" + "\n".join(f"- {f}" for f in files_modified)
    
    # Build test output section
    test_section = ""
    if test_output:
        test_section = f"\n\nTEST OUTPUT (already executed):\n```\n{test_output[:3000]}\n```"
    
    # Build already-implemented section
    already_impl_section = ""
    if already_implemented_claim:
        already_impl_section = f"""

⚠️ AGENT CLAIMS: ALREADY IMPLEMENTED
The agent claims this work was already done. They did NOT modify files.
AGENT'S CLAIM: {already_implemented_claim}

YOUR JOB: Use your tools to VERIFY this claim. Check if the files actually exist
and contain the expected content. Don't just trust their word.
"""
    
    # System prompt
    system_prompt = f"""You are a QA Engineer verifying that a coding task was completed correctly.

## Your Tools
You have these tools to verify the agent's work:
- `read_file(path)` - Read file contents from the agent's worktree
- `file_exists(path)` - Check if a file exists  
- `list_directory(path)` - See what files are in a directory
- `run_tests(command)` - Execute a test command and get output

## Task Being Evaluated
Title: {task.get('title', 'N/A')}
Description: {task.get('description', 'N/A')}

## Acceptance Criteria (MUST BE MET)
{criteria_text}

## Agent's Work Summary
{aar_summary if aar_summary else "(No summary provided)"}
{files_section}
{test_section}
{already_impl_section}

## Your Verification Process
1. **CHECK FILES**: Use `file_exists` and `read_file` to verify claimed files exist
2. **VERIFY CONTENT**: Read key files to confirm they have correct content
3. **CHECK CRITERIA**: For each acceptance criterion, verify it's satisfied
4. **RUN TESTS IF NEEDED**: Use `run_tests` if tests should be verified

## Response Format
After verification, respond with ONLY this JSON (no markdown, no extra text):

{{"verdict": "PASS", "feedback": "explanation of what was verified", "focus": ""}}

or

{{"verdict": "FAIL", "feedback": "what is wrong or missing", "focus": "what needs to be fixed"}}

## Rules
- Use tools to VERIFY claims, don't just trust text
- Check at least one file to confirm it exists and has content
- Max {MAX_TOOL_CALLS} tool calls allowed
- If you can't verify → FAIL with reason
"""

    # Create agent
    agent = create_react_agent(llm, tools)
    
    # Run agent
    try:
        logger.info(f"  [QA Agent] Invoking agent with {len(tools)} tools...")
        
        result = await agent.ainvoke(
            {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content="Verify this task completion. Use your tools to check files, then return your verdict as JSON.")
                ]
            },
            config={"recursion_limit": 50}  # Allow more turns for complex verification
        )
        
        # Count tool calls
        tool_call_count = 0
        for msg in result.get("messages", []):
            if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                tool_call_count += len(msg.tool_calls)
        
        logger.info(f"  [QA Agent] Completed with {tool_call_count} tool calls")
        
        # Extract final response
        final_message = result.get("messages", [])[-1] if result.get("messages") else None
        
        if final_message and hasattr(final_message, 'content'):
            content = str(final_message.content).strip()
            
            # Parse JSON response
            json_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', content, re.DOTALL | re.IGNORECASE)
            if json_match:
                try:
                    verdict_json = json.loads(json_match.group())
                    verdict = verdict_json.get("verdict", "").upper()
                    feedback = verdict_json.get("feedback", "No feedback")
                    focus = verdict_json.get("focus", "")
                    
                    logger.info(f"  [QA Agent] Verdict: {verdict}")
                    return {
                        "passed": verdict == "PASS",
                        "feedback": feedback,
                        "focus": focus
                    }
                except json.JSONDecodeError:
                    logger.warning(f"  [QA Agent] Failed to parse JSON from: {content[:200]}")
            
            # Fallback: try to infer from content
            content_upper = content.upper()
            if "PASS" in content_upper and "FAIL" not in content_upper:
                return {
                    "passed": True,
                    "feedback": f"QA Agent verified (inferred PASS): {content[:500]}",
                    "focus": ""
                }
            elif "FAIL" in content_upper:
                return {
                    "passed": False,
                    "feedback": f"QA Agent found issues: {content[:500]}",
                    "focus": "Review agent feedback"
                }
        
        # If we couldn't parse response, fail safe
        logger.error(f"  [QA Agent] Could not parse response")
        return {
            "passed": False,
            "feedback": "QA Agent could not produce a valid verdict",
            "focus": "Check QA agent logs"
        }
        
    except Exception as e:
        logger.error(f"  [QA Agent] Error: {e}")
        return {
            "passed": False,
            "feedback": f"QA Agent error: {str(e)}",
            "focus": "Fix QA agent error"
        }
