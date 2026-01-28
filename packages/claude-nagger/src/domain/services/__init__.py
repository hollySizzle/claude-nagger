"""ドメインサービス"""

from .hook_manager import HookManager
from .file_convention_matcher import FileConventionMatcher
from .command_convention_matcher import CommandConventionMatcher
from .base_convention_matcher import BaseConventionMatcher
from .subagent_marker_manager import SubagentMarkerManager
from .rule_suggester import RuleSuggester, PatternSuggestion

__all__ = [
    'HookManager',
    'FileConventionMatcher',
    'CommandConventionMatcher',
    'BaseConventionMatcher',
    'SubagentMarkerManager',
    'RuleSuggester',
    'PatternSuggestion',
]
