"""
Tool Safety Wrapper
===================
Wraps tools to catch exceptions and return error messages instead of crashing.
"""

from functools import wraps
from typing import Callable, Any


def safe_tool(func: Callable) -> Callable:
    """
    Decorator that wraps a tool function to catch exceptions and return error messages.
    
    This prevents tool errors from crashing the agent loop. Instead, the LLM sees the
    error message in the ToolMessage and can retry or adjust its approach.
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            return f"Error: File not found - {str(e)}\nThe file or directory does not exist. Please check the path and try again."
        except PermissionError as e:
            return f"Error: Permission denied - {str(e)}\nYou do not have permission to access this file or directory."
        except ValueError as e:
            # ValueError is used for validation errors (e.g., path outside workspace)
            return f"Error: {str(e)}"
        except Exception as e:
            # Catch any other exceptions and return as error message
            error_type = type(e).__name__
            return f"Error: {error_type} - {str(e)}\nThe operation failed. Please check your input and try again."
    
    return wrapper
