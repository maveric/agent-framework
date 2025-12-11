"""
Metrics API Routes
==================
Prometheus metrics endpoint for observability.
"""

import logging
from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from metrics import git_metrics, task_metrics, llm_metrics, dispatch_metrics

logger = logging.getLogger(__name__)

# Create router - no /api/v1 prefix since this is a standard Prometheus endpoint
router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics():
    """
    Prometheus metrics endpoint.

    This endpoint is scraped by Prometheus to collect metrics about:
    - Git operations (merge duration, conflicts, etc.)
    - Task execution (duration, retries, etc.)
    - LLM API calls (requests, tokens, cost)
    - Dispatch loop performance

    Access via http://localhost:8000/metrics
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
