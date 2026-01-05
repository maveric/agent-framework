"""
Research Handler
================
Conducts research using web search and synthesizes findings.
"""

import logging
from typing import Dict, Any

from orchestrator_types import Task, WorkerProfile, WorkerResult

# Import tools (ASYNC versions for non-blocking execution)
from tools import (
    read_file_async as read_file,
    write_file_async as write_file,
    list_directory_async as list_directory
)
from tools.search_tools import get_tavily_search_tool

from ..tools_binding import _bind_tools
from ..execution import _execute_react_loop

logger = logging.getLogger(__name__)


async def _research_handler(task: Task, state: Dict[str, Any], config: Dict[str, Any] = None) -> WorkerResult:
    """
    Research handler with web search capabilities.
    
    Workflow:
    1. Agent analyzes task and formulates search queries
    2. Uses Tavily search to gather information
    3. Synthesizes findings into a comprehensive report
    4. Saves report to research-results/ directory
    """
    logger.info(f"Research handler: Starting research for task {task.id}")
    
    # Get Tavily search tool
    try:
        search_tool = get_tavily_search_tool(max_results=5)
    except ValueError as e:
        logger.error(f"Failed to initialize search tool: {e}")
        # Provide fallback with limited tools
        search_tool = None
    
    # Build tool list
    tools = [read_file, write_file, list_directory]
    if search_tool:
        tools.append(search_tool)
        logger.info("✅ Tavily search tool enabled")
    else:
        logger.warning("⚠️ Search tool unavailable - research will be limited")
    
    # Bind tools to workspace
    tools = _bind_tools(tools, state, WorkerProfile.RESEARCHER)
    
    system_prompt = """You are a research specialist.

Your goal is to gather comprehensive information on the given topic and synthesize findings into a clear, well-structured report.

## Research Process:
1. **Understand the Topic**: Break down the research question into key aspects
2. **Search**: Use the tavily_search_results tool to find relevant information
   - Formulate specific, targeted queries
   - Search multiple times from different angles if needed
3. **Analyze**: Review search results critically
   - Look for authoritative sources
   - Cross-reference information
   - Note conflicting viewpoints
4. **Synthesize**: Write a comprehensive report covering:
   - Executive summary
   - Key findings
   - Detailed analysis
   - Recommendations (if applicable)
   - Sources/references

## Output:
- Save your final report to: `research-results/report.md`
- Use clear headings and bullet points
- Include sources for key claims
- Keep it actionable and relevant to the task

## Available Tools:
- `tavily_search_results`: Search the web (returns title, url, content, score)
- `write_file`: Save your research report
- `read_file`: Read existing files if needed
- `list_directory`: Check directory contents

Work systematically and thoroughly. Quality research takes time!"""
    
    # INJECT PHOENIX RETRY CONTEXT if this is a retry attempt
    from ..utils import get_phoenix_retry_context
    phoenix_context = get_phoenix_retry_context(task)
    if phoenix_context:
        system_prompt = f"{phoenix_context}\n\n{system_prompt}"

    return await _execute_react_loop(task, tools, system_prompt, state, config)
