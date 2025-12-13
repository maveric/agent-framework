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
        # provider="anthropic",
        # model_name="claude-3-5-sonnet-20241022",
        provider="openai",
        model_name="gpt-4.1",
        temperature=0.7
    ))
    
    worker_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        # provider="anthropic",
        # model_name="claude-3-5-sonnet-20241022",
        provider="glm",
        model_name="glm-4.6",
        temperature=0.5
    ))

    planner_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        # provider="anthropic",
        # model_name="claude-3-5-sonnet-20241022",
        provider="openrouter",
        model_name="x-ai/grok-4.1-fast",
        temperature=0.5
    ))

    researcher_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        # provider="anthropic",
        # model_name="claude-3-5-sonnet-20241022",
        provider="local",
        model_name="qwen3-coder:30b",
        temperature=0.5
    ))
    
    # Per-worker-profile model configurations (optional - falls back to worker_model)
    # These allow different models for different worker types
    # planner_model: Optional[ModelConfig] = None  # For planning tasks - can use smarter model
    coder_model: Optional[ModelConfig] = None    # For build tasks - can use faster model
    tester_model: Optional[ModelConfig] = None   # For test tasks - can use faster model
    # researcher_model: Optional[ModelConfig] = None  # For research tasks
    writer_model: Optional[ModelConfig] = None   # For documentation/writing tasks
    
    strategist_model: ModelConfig = field(default_factory=lambda: ModelConfig(
        # provider="anthropic",
        # model_name="claude-3-5-sonnet-20241022",
        provider="openrouter",
        model_name="minimax/minimax-m2",
        temperature=0.3
    ))
    
    # Retry configuration
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    
    # Webhook configuration
    webhook_config: WebhookConfig = field(default_factory=WebhookConfig)
    
    # Execution limits
    max_concurrent_workers: int = 5  # Limit parallel LLM calls for rate limits
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
    checkpoint_mode: str = "sqlite"  # "sqlite", "postgres", or "memory"
    
    # PostgreSQL connection (only used if checkpoint_mode="postgres")
    postgres_uri: Optional[str] = None  # Falls back to POSTGRES_URI env var
    
    # Framework data paths (OUTSIDE agent workspaces to avoid gitignore conflicts)
    # Set to absolute path, e.g., "F:/coding/agent-framework/run-data"
    # If None, defaults to agent-framework/run-data directory
    run_data_base_path: Optional[str] = "F:/coding/agent-stuff/run-data"
    
    # Dev/Test flags
    mock_mode: bool = False
    
    def get_run_data_path(self, run_id: str) -> "Path":
        """Get the path for storing run-specific data (worktrees, logs).
        
        Structure: {run_data_base_path}/{run_id}/
            ├── worktrees/
            └── llm_logs/
        """
        from pathlib import Path
        
        if self.run_data_base_path:
            base = Path(self.run_data_base_path)
        else:
            # Default: agent-framework/run-data
            base = Path(__file__).parent.parent / "run-data"
        
        run_path = base / run_id
        run_path.mkdir(parents=True, exist_ok=True)
        return run_path
    
    def get_worktree_base(self, run_id: str) -> "Path":
        """Get worktree base path for a run."""
        return self.get_run_data_path(run_id) / "worktrees"
    
    def get_llm_logs_path(self, run_id: str) -> "Path":
        """Get LLM logs path for a run."""
        return self.get_run_data_path(run_id) / "llm_logs"

