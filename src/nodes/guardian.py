"""
Agent Orchestrator — Guardian Node
==================================
Version 2.0 — December 2025

Guardian monitors agent execution and injects nudges when agents drift off-course.
Called synchronously every N tool calls during ReAct loop execution.
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage

from orchestrator_types import (
    Task, GuardianVerdict, GuardianNudge, GuardianTrajectory, NudgeTone
)
from llm_client import get_llm
from config import OrchestratorConfig

logger = logging.getLogger(__name__)

# Guardian analysis prompt
GUARDIAN_PROMPT = """You are a Guardian monitoring an AI agent's work. Your job is to detect when the agent is drifting off-task and provide course corrections.

## Task Being Executed
**Title:** {task_title}
**Description:** {task_description}
**Acceptance Criteria:**
{acceptance_criteria}

## Recent Agent Activity (last {message_count} messages)
{recent_messages}

## Your Analysis Task
Evaluate whether the agent is making progress toward the task objectives.

Consider:
1. Is the agent working on the assigned task, or has it drifted to unrelated work?
2. Is the agent making progress, or is it stuck in a loop (repeating similar actions)?
3. Is the agent's approach reasonable for the task?
4. Has the agent lost sight of the acceptance criteria?

## Response Format
Respond with a JSON object (no markdown, just raw JSON):
{{
    "verdict": "on_track" | "drifting" | "blocked" | "stalled",
    "confidence": 0-100,
    "reasoning": "Brief explanation of your assessment",
    "nudge": "Message to inject if agent needs redirection (null if on_track)"
}}

**Verdict meanings:**
- "on_track": Agent is working appropriately toward the goal
- "drifting": Agent is doing unrelated work or going off on tangents
- "blocked": Agent is stuck, repeating actions without progress
- "stalled": Agent seems to have stopped making meaningful progress

**Nudge guidelines:**
- If on_track, nudge should be null
- If drifting/blocked/stalled, provide a clear, actionable redirection
- Write the nudge as if YOU are the user giving feedback to the agent
- Be specific about what the agent should focus on
- Keep nudges concise (1-3 sentences)
"""


def _format_messages_for_guardian(messages: List[BaseMessage], max_messages: int = 20) -> str:
    """Format recent messages for guardian analysis."""
    recent = messages[-max_messages:] if len(messages) > max_messages else messages

    formatted = []
    for i, msg in enumerate(recent):
        if isinstance(msg, SystemMessage):
            # Skip system messages - guardian already has task context
            continue
        elif isinstance(msg, HumanMessage):
            formatted.append(f"[USER]: {msg.content[:500]}...")
        elif isinstance(msg, AIMessage):
            content = msg.content[:300] if msg.content else ""
            tool_calls = ""
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                tool_names = [tc.get('name', 'unknown') for tc in msg.tool_calls]
                tool_calls = f" [Calling tools: {', '.join(tool_names)}]"
            formatted.append(f"[AGENT]: {content}{tool_calls}")
        elif isinstance(msg, ToolMessage):
            # Truncate tool results
            content = str(msg.content)[:200]
            formatted.append(f"[TOOL RESULT]: {content}...")

    return "\n".join(formatted) if formatted else "(No recent activity)"


async def check_agent_alignment(
    task: Task,
    messages: List[BaseMessage],
    config: OrchestratorConfig,
    iteration_count: int
) -> Optional[GuardianNudge]:
    """
    Check if agent is aligned with task objectives.

    Called every N iterations during ReAct loop.
    Returns a GuardianNudge if intervention is needed, None if on_track.

    Args:
        task: The task being executed
        messages: Current message history from ReAct loop
        config: Orchestrator config (contains guardian settings)
        iteration_count: Current iteration number (for logging)

    Returns:
        GuardianNudge if intervention needed, None if agent is on track
    """
    import json

    logger.info(f"  [GUARDIAN] Checking alignment at iteration {iteration_count} for task {task.id}")

    # Format task info
    acceptance_criteria = "\n".join(f"- {c}" for c in task.acceptance_criteria) if task.acceptance_criteria else "- None specified"

    # Format recent messages
    context_window = config.guardian_context_window
    recent_messages = _format_messages_for_guardian(messages, context_window)

    # Build prompt
    prompt = GUARDIAN_PROMPT.format(
        task_title=task.title,
        task_description=task.description,
        acceptance_criteria=acceptance_criteria,
        message_count=min(len(messages), context_window),
        recent_messages=recent_messages
    )

    # Call guardian model (Haiku by default - fast and cheap)
    try:
        llm = get_llm(config.guardian_model)
        response = await llm.ainvoke(prompt)
        response_text = response.content if hasattr(response, 'content') else str(response)

        # Parse JSON response
        # Handle potential markdown wrapping
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        result = json.loads(response_text.strip())

        verdict_str = result.get("verdict", "on_track")
        confidence = result.get("confidence", 100)
        reasoning = result.get("reasoning", "")
        nudge_text = result.get("nudge")

        # Map string to enum
        verdict_map = {
            "on_track": GuardianVerdict.ON_TRACK,
            "drifting": GuardianVerdict.DRIFTING,
            "blocked": GuardianVerdict.BLOCKED,
            "stalled": GuardianVerdict.STALLED,
        }
        verdict = verdict_map.get(verdict_str, GuardianVerdict.ON_TRACK)

        logger.info(f"  [GUARDIAN] Verdict: {verdict.value} (confidence: {confidence}%)")
        if reasoning:
            logger.info(f"  [GUARDIAN] Reasoning: {reasoning[:100]}...")

        # If on track, no nudge needed
        if verdict == GuardianVerdict.ON_TRACK:
            return None

        # Determine tone based on confidence (inverted - lower confidence in being on track = more urgent)
        if confidence >= 80:
            tone = NudgeTone.FIRM
        elif confidence >= 50:
            tone = NudgeTone.DIRECT
        else:
            tone = NudgeTone.GENTLE

        # Create nudge
        nudge = GuardianNudge(
            task_id=task.id,
            verdict=verdict,
            message=nudge_text or f"Please refocus on the task: {task.title}",
            detected_issue=reasoning,
            alignment_score=100 - confidence,  # Invert: high confidence in drift = low alignment
            trajectory=GuardianTrajectory.STABLE,  # Would need history to determine
            tone=tone,
            timestamp=datetime.now()
        )

        logger.info(f"  [GUARDIAN] Nudge ({tone.value}): {nudge.message[:100]}...")

        return nudge

    except json.JSONDecodeError as e:
        logger.warning(f"  [GUARDIAN] Failed to parse response as JSON: {e}")
        logger.debug(f"  [GUARDIAN] Raw response: {response_text[:500]}")
        return None
    except Exception as e:
        logger.error(f"  [GUARDIAN] Error during alignment check: {e}")
        return None


def guardian_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Guardian graph node (for future use if we add guardian as graph node).

    Currently, guardian is called inline during ReAct execution via
    check_agent_alignment(), not as a separate graph node.
    """
    # This stub remains for potential future graph-level guardian checks
    return {}
