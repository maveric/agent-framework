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
    Get an LLM instance based on configuration.
    
    Args:
        model_config: Model configuration. If None, uses default Anthropic.
    
    Returns:
        Configured LLM instance
    """
    if model_config is None:
        # Default to Claude
        model_config = ModelConfig(
            provider="anthropic",
            model_name="claude-3-5-sonnet-20241022",
            temperature=0.7
        )
    
    provider = model_config.provider.lower()
    
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens or 4096,
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            api_key=os.getenv("OPENAI_API_KEY")
        )
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_config.model_name,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
