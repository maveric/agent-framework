"""
Agent Orchestrator — LLM Client
===============================
Version 1.0 — November 2025

Wrapper for LLM interactions with retry logic and error handling.

Supported Providers:
- anthropic: Claude models (requires ANTHROPIC_API_KEY)
- openai: GPT models (requires OPENAI_API_KEY)
- google: Gemini models (requires GOOGLE_API_KEY)
- glm: Zhipu AI models (requires GLM_API_KEY)
- openrouter: OpenRouter proxy (requires OPENROUTER_API_KEY)
- local: Ollama local models (requires Ollama running, optional OLLAMA_BASE_URL)

Example:
    # Use Ollama locally
    from config import ModelConfig
    config = ModelConfig(
        provider="local",
        model_name="llama3.2",  # or "qwen2.5-coder:7b", etc.
        temperature=0.7
    )
    llm = get_llm(config)
    
    # Set custom Ollama URL via environment variable:
    # OLLAMA_BASE_URL=http://192.168.1.100:11434/v1
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
            # base_url="https://open.bigmodel.cn/api/paas/v4/",  # GLM API endpoint
            base_url="https://api.z.ai/api/coding/paas/v4",
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
    elif provider == "local":
        # Local Ollama server (OpenAI-compatible API)
        from langchain_openai import ChatOpenAI
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        llm = ChatOpenAI(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            api_key="ollama",  # Ollama doesn't require an API key, but langchain needs something
            base_url=base_url,
            max_retries=3,  # Fewer retries for local
            timeout=120.0,  # Longer timeout for local inference
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
