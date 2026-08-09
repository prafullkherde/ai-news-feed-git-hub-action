"""DEPRECATED: Settings moved to config/Settings.py

This file is a small compatibility shim that imports everything from
config/Settings.py so existing imports of
Multi-Agent-Stock-Debate/Settings.py continue to work.
"""

try:
    from config.Settings import *  # noqa: F401,F403
except Exception as e:
    raise ImportError("Settings module moved to config/Settings.py. Update imports or ensure config/ is on PYTHONPATH.") from e
