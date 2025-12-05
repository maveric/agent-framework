"""
Agent Orchestrator — LLM Client
===============================
Version 1.0 — November 2025

Wrapper for LLM interactions with retry logic and error handling.
"""

from typing import Optional
from config import ModelConfig
import os


def get_llm(model_config: Optional[ModelConfig] = None):
    """
    Get an LLM instance based on configuration with built-in retry logic.
    
    Args:
        model_config: Model configuration. If None, uses default Anthropic.
    
    Returns:
        Configured LLM instance with retry handling
    """
    if model_config is None:
        # Default to Claude
        model_config = ModelConfig(
            provider="anthropic",
            model_name="claude-3-5-sonnet-20241022",
            temperature=0.7
        )
    
    provider = model_config.provider.lower()
    
    # Configure LLM with built-in retry and exponential backoff
    # max_retries parameter automatically handles 429 rate limit errors
    # with exponential backoff: 1s, 2s, 4s, 8s, 16s between retries
    
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens or 4096,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            max_retries=5,  # Retry up to 5 times on failures
            timeout=60.0,  # 60 second timeout
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            api_key=os.getenv("OPENAI_API_KEY"),
            max_retries=5,  # Retry up to 5 times on failures
            timeout=60.0,  # 60 second timeout
        )
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            max_retries=5,  # Retry up to 5 times
            timeout=60.0,
        )
    elif provider == "glm":
        # GLM (Zhipu AI) uses OpenAI-compatible API
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            api_key=os.getenv("GLM_API_KEY"),
            base_url="https://open.bigmodel.cn/api/paas/v4/",  # GLM API endpoint
            max_retries=5,
            timeout=60.0,
        )
    elif provider == "openrouter":
        # OpenRouter uses OpenAI-compatible API
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",  # OpenRouter API endpoint
            max_retries=5,
            timeout=60.0,
            default_headers={
                "HTTP-Referer": "https://github.com/yourusername/agent-framework",  # Optional but recommended
                "X-Title": "Agent Framework"  # Optional but recommended
            }
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    
    return llm


async def ainvoke_llm(llm, messages, **kwargs):
    """
    Async wrapper for LLM invocation.
    
    LangChain LLMs support async via .ainvoke() method.
    This wrapper provides a consistent interface.
    
    Args:
        llm: LLM instance from get_llm()
        messages: List of messages to send
        **kwargs: Additional arguments to pass to ainvoke
        
    Returns:
        LLM response
    """
    return await llm.ainvoke(messages, **kwargs)


async def astream_llm(llm, messages, **kwargs):
    """
    Async streaming wrapper for LLM invocation.
    
    Args:
        llm: LLM instance from get_llm()
        messages: List of messages to send
        **kwargs: Additional arguments
        
    Yields:
        Chunks of the LLM response
    """
    async for chunk in llm.astream(messages, **kwargs):
        yield chunk
