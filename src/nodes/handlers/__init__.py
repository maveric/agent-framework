"""
Worker handlers for different task types.

TDD Note: _test_architect_handler writes tests BEFORE implementation (RED phase).
         _test_handler validates implementations AFTER code is written (legacy).
"""

from .code_handler import _code_handler
from .plan_handler import _plan_handler
from .test_handler import _test_handler
from .test_architect_handler import _test_architect_handler  # TDD: writes failing tests
from .research_handler import _research_handler
from .write_handler import _write_handler
from .merge_handler import _merge_handler

__all__ = [
    '_code_handler',
    '_plan_handler',
    '_test_handler',
    '_test_architect_handler',  # TDD: writes failing tests from specs
    '_research_handler',
    '_write_handler',
    '_merge_handler',
]
