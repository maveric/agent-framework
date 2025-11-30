"""
Agent Orchestrator — Configuration
==================================
Version 1.0 — November 2025

Configuration classes for the orchestrator.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ModelConfig:
    """LLM model configuration."""
    provider: str  # "anthropic", "openai", "google", etc.
    model_name: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None


@dataclass
class RetryConfig:
    """Retry configuration for LLM calls."""
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0


@dataclass
class WebhookConfig:
    """Webhook configuration for notifications."""
    enabled: bool = False
    url: Optional[str] = None
    events: list[str] = field(default_factory=lambda: ["task_complete", "run_complete", "error"])


@dataclass
class OrchestratorConfig:
    """Main orchestrator configuration."""
    
    # Model configurations for different roles
    director_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        temperature=0.7
    ))
    
    worker_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        temperature=0.5
    ))
    
    strategist_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        temperature=0.3
    ))
    
    # Retry configuration
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    
    # Webhook configuration
    webhook_config: WebhookConfig = field(default_factory=WebhookConfig)
    
    # Execution limits
    max_concurrent_workers: int = 3
    max_iterations_per_task: int = 10
    max_total_iterations: int = 100
    
    # Timeouts (seconds)
    worker_timeout: int = 300  # 5 minutes
    director_timeout: int = 60
    
    # Feature flags
    enable_guardian: bool = False  # Drift detection
    enable_git_worktrees: bool = False  # Git isolation per task
    enable_webhooks: bool = False
    
    # Checkpointing
    checkpoint_dir: str = "./checkpoints"
    checkpoint_mode: str = "sqlite"  # "sqlite" or "memory"
    
    # Dev/Test flags
    mock_mode: bool = False
