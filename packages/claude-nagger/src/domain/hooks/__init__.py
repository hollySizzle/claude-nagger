"""フック処理ドメインモジュール"""

# 循環インポート回避のため、動的インポートに変更
__all__ = ['BaseHook', 'ExitCode', 'ImplementationDesignHook']


def get_base_hook():
    from .base_hook import BaseHook
    return BaseHook


def get_exit_code():
    from .base_hook import ExitCode
    return ExitCode


def get_implementation_design_hook():
    from .implementation_design_hook import ImplementationDesignHook
    return ImplementationDesignHook