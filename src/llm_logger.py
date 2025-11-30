"""
LLM Request Logger
==================
Logs all requests sent to LLM for debugging.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

LOG_DIR = Path("llm_logs")
LOG_DIR.mkdir(exist_ok=True)

def log_llm_request(
    task_id: str,
    messages: List[Any],
    tools: List[Any],
    config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Log an LLM request and return stats.
    
    Returns:
        dict with 'total_chars', 'estimated_tokens', 'message_count', 'tool_count'
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"request_{task_id}_{timestamp}.json"
    
    # Calculate stats
    total_chars = sum(len(str(m.content)) for m in messages if hasattr(m, 'content'))
    estimated_tokens = total_chars // 4
    
    # Create log entry
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "task_id": task_id,
        "message_count": len(messages),
        "tool_count": len(tools),
        "total_chars": total_chars,
        "estimated_tokens": estimated_tokens,
        "messages": [
            {
                "type": type(m).__name__,
                "content": str(m.content)[:500] + "..." if len(str(m.content)) > 500 else str(m.content)
            }
            for m in messages if hasattr(m, 'content')
        ],
        "tools": [
            {
                "name": getattr(t, '__name__', str(t)),
                "doc": (getattr(t, '__doc__', '')[:200] + "...") if getattr(t, '__doc__', '') and len(getattr(t, '__doc__', '')) > 200 else getattr(t, '__doc__', '')
            }
            for t in tools
        ],
        "config": config or {}
    }
    
    # Write to log file
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(log_entry, f, indent=2)
    
    return {
        "total_chars": total_chars,
        "estimated_tokens": estimated_tokens,
        "message_count": len(messages),
        "tool_count": len(tools),
        "log_file": str(log_file)
    }


def validate_request_size(stats: Dict[str, Any], max_chars: int = 100000) -> None:
    """
    Validate request size and raise error if too large.
    
    Args:
        stats: Stats dict from log_llm_request
        max_chars: Maximum allowed characters (default: 100K)
    
    Raises:
        ValueError: If request exceeds size limit
    """
    if stats["total_chars"] > max_chars:
        raise ValueError(
            f"Request too large: {stats['total_chars']} chars ({stats['estimated_tokens']} tokens estimated). "
            f"Maximum allowed: {max_chars} chars. "
            f"Check log file: {stats['log_file']}"
        )


def log_llm_response(
    task_id: str,
    result: Any,
    files_modified: List[str] = None,
    status: str = "unknown"
) -> None:
    """
    Log the LLM response and execution results.
    
    Args:
        task_id: Task identifier
        result: Agent result object
        files_modified: List of files that were modified
        status: Task status (complete/failed)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"response_{task_id}_{timestamp}.json"
    
    # Extract messages from result
    messages = []
    if hasattr(result, 'get') and 'messages' in result:
        for msg in result['messages']:
            messages.append({
                "type": type(msg).__name__,
                "content": str(msg.content)[:1000] + "..." if len(str(getattr(msg, 'content', ''))) > 1000 else str(getattr(msg, 'content', '')),
                "tool_calls": getattr(msg, 'tool_calls', [])[:3] if hasattr(msg, 'tool_calls') else []
            })
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "task_id": task_id,
        "status": status,
        "files_modified": files_modified or [],
        "file_count": len(files_modified) if files_modified else 0,
        "messages": messages,
        "message_count": len(messages)
    }
    
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(log_entry, f, indent=2)
    
    print(f"  [LOG] Response saved: {log_file}", flush=True)
