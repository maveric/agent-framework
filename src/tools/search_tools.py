"""
Search Tools for Research Worker
=================================

LangChain-integrated web search tools using Tavily.
Tavily is optimized for AI agents and provides clean, structured results.

Uses dedicated langchain-tavily package (not langchain-community).
"""

import os
import logging
from typing import List, Dict, Any
from langchain_tavily import TavilySearch

logger = logging.getLogger(__name__)


def get_tavily_search_tool(max_results: int = 5) -> TavilySearch:
    """
    Get configured Tavily search tool.
    
    Args:
        max_results: Maximum number of search results to return
        
    Returns:
        Configured TavilySearch tool
        
    Raises:
        ValueError: If TAVILY_API_KEY is not set
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError(
            "TAVILY_API_KEY not found in environment. "
            "Get your key at https://app.tavily.com"
        )
    
    return TavilySearch(
        max_results=max_results,
        topic="general",
        # search_depth="advanced",  # Optional: "basic" or "advanced"
        # include_answer=True,       # Optional: include AI answer
        # include_domains=[],        # Optional: restrict to specific domains
        # exclude_domains=[],        # Optional: exclude specific domains
    )


# Tool wrapper for direct invocation (if needed)
async def web_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Search the web using Tavily.
    
    Args:
        query: Search query
        max_results: Maximum number of results
        
    Returns:
        List of search results, each containing:
        - title: Page title
        - url: Page URL
        - content: Page content snippet
        - score: Relevance score (0-1)
        
    Example:
        results = await web_search("FastAPI authentication best practices")
        for result in results:
            print(f"{result['title']}: {result['url']}")
    """
    try:
        tool = get_tavily_search_tool(max_results=max_results)
        
        # Tavily tool returns synchronously
        results = tool.invoke({"query": query})
        
        logger.info(f"Tavily search: '{query}' returned {len(results)} results")
        return results
        
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        raise


# Export for tool binding
__all__ = [
    "get_tavily_search_tool",
    "web_search",
]
