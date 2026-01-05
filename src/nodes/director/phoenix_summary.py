"""
Phoenix Retry Summarization
===========================

When a task fails and Phoenix retries it, summarize the previous attempt's
conversation to provide focused context without bloating tokens.
"""

import logging
from typing import List, Optional, Dict, Any

from langchain_core.messages import BaseMessage, AIMessage, ToolMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


async def summarize_failed_attempt(
    task_id: str,
    messages: List[BaseMessage],
    qa_feedback: Optional[str],
    previous_summary: Optional[str] = None
) -> str:
    """
    Summarize a failed task attempt for Phoenix retry.
    
    Args:
        task_id: The task ID being summarized
        messages: The full conversation history from the failed attempt
        qa_feedback: The QA verdict feedback that caused the failure
        previous_summary: If this is retry #2+, the summary from the prior attempt
        
    Returns:
        A structured summary suitable for injection into retry system prompt
    """
    from llm_client import get_llm
    from config import OrchestratorConfig
    
    orch_config = OrchestratorConfig()
    llm = get_llm(orch_config.strategist_model)  # Use strategist model for analysis
    
    # Build a condensed view of the conversation
    conversation_digest = _extract_conversation_digest(messages)
    
    # Count tool statistics
    tool_stats = _count_tool_stats(messages)
    
    system_prompt = """You are a technical analyst summarizing a failed task attempt.

Your summary will be used by the NEXT attempt to avoid repeating mistakes.

RULES:
1. Be CONCISE - the summary will be injected into a system prompt
2. Focus on ACTIONABLE information:
   - What files were created/modified?
   - What worked (successful operations)?
   - What failed and WHY?
   - What decisions were made and their outcomes?
3. Include the QA feedback that caused the failure
4. Provide specific recommendations for the retry
5. Do NOT include code snippets - just describe what the code does
6. Keep total length under 500 words

OUTPUT FORMAT:
### Previous Attempt Summary

**Files Modified:**
- file1.py - description of what was done
- file2.js - description of what was done

**What Worked:**
- Successfully created X
- Successfully configured Y

**What Failed:**
- Failed to do X because Y
- Error encountered: Z

**QA Failure Reason:**
[The QA verdict that caused this retry]

**Recommendations for Retry:**
1. Do X instead of Y
2. Make sure to Z before completing
"""

    # Build the user message with all context
    user_content = f"""Summarize this failed task attempt:

## Tool Call Statistics
- Total tool calls: {tool_stats['total']}
- Successful: {tool_stats['success']}
- Failed/Error: {tool_stats['failed']}

## QA Feedback (why it failed)
{qa_feedback or "No specific QA feedback provided"}

## Conversation Digest
{conversation_digest}
"""

    # Include previous summary if this is retry #2+
    if previous_summary:
        user_content += f"""

## Previous Retry Context
The following is from an EARLIER failed attempt. Include relevant context but don't duplicate:
{previous_summary}
"""

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content)
        ])
        
        summary = str(response.content).strip()
        logger.info(f"  [PHOENIX] Generated summary for {task_id[:12]} ({len(summary)} chars)")
        return summary
        
    except Exception as e:
        logger.error(f"  [PHOENIX] Summarization failed for {task_id[:12]}: {e}")
        # Fallback: return a basic summary with just the QA feedback
        return f"""### Previous Attempt Summary

**Summarization Failed:** {str(e)[:100]}

**QA Failure Reason:**
{qa_feedback or "Unknown failure reason"}

**Recommendation:** Review the task requirements carefully and try a different approach.
"""


def _extract_conversation_digest(messages: List[BaseMessage]) -> str:
    """
    Extract key information from messages without full content.
    Focus on tool calls, their arguments, and results.
    """
    digest_lines = []
    
    for i, msg in enumerate(messages):
        if isinstance(msg, SystemMessage):
            # Skip system message - it's the standard prompt
            continue
            
        elif isinstance(msg, HumanMessage):
            content = str(msg.content)[:200]
            if "[GUIDANCE]" in content:
                digest_lines.append(f"[Guardian Nudge]: {content[11:150]}...")
            elif i == 1:  # First human message is usually the task
                digest_lines.append(f"[Task]: {content[:150]}...")
                
        elif isinstance(msg, AIMessage):
            # Extract tool calls
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_name = tc.get('name', 'unknown')
                    args = tc.get('args', {})
                    
                    # Summarize args based on tool type
                    if tool_name in ['write_file', 'append_file']:
                        path = args.get('path', '?')
                        content_len = len(args.get('content', ''))
                        digest_lines.append(f"[Tool] {tool_name}('{path}', {content_len} chars)")
                    elif tool_name == 'read_file':
                        path = args.get('path', '?')
                        digest_lines.append(f"[Tool] {tool_name}('{path}')")
                    elif tool_name == 'run_shell':
                        cmd = args.get('command', '?')[:80]
                        digest_lines.append(f"[Tool] {tool_name}('{cmd}')")
                    elif tool_name == 'run_python':
                        code = args.get('code', '')[:50]
                        digest_lines.append(f"[Tool] {tool_name}('{code}...')")
                    elif tool_name == 'list_directory':
                        path = args.get('path', '.')
                        digest_lines.append(f"[Tool] {tool_name}('{path}')")
                    elif tool_name == 'create_subtasks':
                        count = len(args.get('subtasks', []))
                        digest_lines.append(f"[Tool] {tool_name}({count} subtasks)")
                    else:
                        # Generic tool summary
                        arg_summary = str(args)[:60]
                        digest_lines.append(f"[Tool] {tool_name}({arg_summary})")
            else:
                # AI thinking/response without tool call
                content = str(msg.content)[:100] if msg.content else ""
                if content:
                    digest_lines.append(f"[AI]: {content}...")
                    
        elif isinstance(msg, ToolMessage):
            content = str(msg.content)
            # Check for errors
            is_error = any(err in content.lower() for err in ['error', 'failed', 'exception', 'denied', 'blocked'])
            
            if is_error:
                # Include error details
                error_summary = content[:200]
                digest_lines.append(f"[Result] ❌ ERROR: {error_summary}")
            else:
                # Just note success
                result_preview = content[:80] if len(content) < 100 else f"{content[:50]}... ({len(content)} chars)"
                digest_lines.append(f"[Result] ✅ {result_preview}")
    
    return "\n".join(digest_lines[-50:])  # Limit to last 50 entries


def _count_tool_stats(messages: List[BaseMessage]) -> Dict[str, int]:
    """Count tool call statistics from messages."""
    stats = {'total': 0, 'success': 0, 'failed': 0}
    
    # Build map of tool_call_id -> result
    results = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = str(msg.content).lower()
            is_error = any(err in content for err in ['error', 'failed', 'exception', 'denied', 'blocked'])
            results[msg.tool_call_id] = not is_error
    
    # Count tool calls
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                stats['total'] += 1
                tc_id = tc.get('id')
                if tc_id in results:
                    if results[tc_id]:
                        stats['success'] += 1
                    else:
                        stats['failed'] += 1
    
    return stats
