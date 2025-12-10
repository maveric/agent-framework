"""
Search Tools for Research Worker
=================================

LangChain-integrated web search tools using Tavily.
Tavily is optimized for AI agents and provides clean, structured results.
"""

import os
import logging
from typing import List, Dict, Any
from langchain_community.tools.tavily_search import TavilySearchResults

logger = logging.getLogger(__name__)


def get_tavily_search_tool(max_results: int = 5) -> TavilySearchResults:
    """
    Get configured Tavily search tool.
    
    Args:
        max_results: Maximum number of search results to return
        
    Returns:
        Configured TavilySearchResults tool
        
    Raises:
        ValueError: If TAVILY_API_KEY is not set
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError(
            "TAVILY_API_KEY not found in environment. "
            "Get your key at https://app.tavily.com"
        )
    
    return TavilySearchResults(
        max_results=max_results,
        api_key=api_key,
        # search_depth="advanced",  # Optional: "basic" or "advanced"
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
