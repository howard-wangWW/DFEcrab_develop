"""
Hook Manager Module
Manages hook system for self-improving agent
"""

from pathlib import Path
from typing import Callable, List, Dict, Any, Optional
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.memory import LearningMemory


class HookManager:
    """Manages hook system for learning events"""

    def __init__(self, workspace: Optional[Path] = None):
        """Initialize hook manager"""
        if workspace is None:
            workspace = Path.home() / '.openclaw' / 'workspace'

        self.workspace = Path(workspace)
        self.memory = LearningMemory(workspace)

        # Hook collections
        self.session_hooks: List[Callable] = []
        self.error_hooks: List[Callable] = []
        self.recovery_hooks: List[Callable] = []
        self.performance_hooks: List[Callable] = []

        # Register default hooks
        self._register_default_hooks()

    def _register_default_hooks(self):
        """Register default learning hooks"""

        def session_learning(session: Dict):
            """Learn from session end"""
            try:
                self.memory.store_session(
                    session.get('id', ''),
                    session.get('duration', 0),
                    session.get('interactions', 0),
                    session.get('success_patterns', [])
                )
            except Exception as e:
                print(f"⚠️  Session learning failed: {e}")

        def error_learning(error: Dict):
            """Learn from errors"""
            try:
                self.memory.store_error(
                    error.get('type', 'Unknown'),
                    error.get('message', ''),
                    error.get('context', {})
                )
            except Exception as e:
                print(f"⚠️  Error learning failed: {e}")

        def recovery_learning(recovery: Dict):
            """Learn from recoveries"""
            try:
                self.memory.store_recovery(
                    recovery.get('method', 'unknown'),
                    recovery.get('context', {})
                )
            except Exception as e:
                print(f"⚠️  Recovery learning failed: {e}")

        def performance_learning(metric: Dict):
            """Learn from performance metrics"""
            try:
                self.memory.store_performance(
                    metric.get('type', 'response_time'),
                    metric.get('value', 0),
                    metric.get('context', {}),
                    metric.get('optimizations', [])
                )
            except Exception as e:
                print(f"⚠️  Performance learning failed: {e}")

        # Register hooks
        self.session_hooks.append(session_learning)
        self.error_hooks.append(error_learning)
        self.recovery_hooks.append(recovery_learning)
        self.performance_hooks.append(performance_learning)

    def on_session_end(self, session: Dict):
        """Trigger session hooks"""
        for hook in self.session_hooks:
            try:
                hook(session)
            except Exception as e:
                print(f"⚠️  Session hook failed: {e}")

    def on_error(self, error: Dict):
        """Trigger error hooks"""
        for hook in self.error_hooks:
            try:
                hook(error)
            except Exception as e:
                print(f"⚠️  Error hook failed: {e}")

    def on_recovery(self, recovery: Dict):
        """Trigger recovery hooks"""
        for hook in self.recovery_hooks:
            try:
                hook(recovery)
            except Exception as e:
                print(f"⚠️  Recovery hook failed: {e}")

    def on_performance(self, metric: Dict):
        """Trigger performance hooks"""
        for hook in self.performance_hooks:
            try:
                hook(metric)
            except Exception as e:
                print(f"⚠️  Performance hook failed: {e}")

    def apply_all(self):
        """Apply all hooks (placeholder for future use)"""
        print("✅ All hooks registered and ready")

    def register_session_hook(self, hook: Callable):
        """Register custom session hook"""
        self.session_hooks.append(hook)

    def register_error_hook(self, hook: Callable):
        """Register custom error hook"""
        self.error_hooks.append(hook)

    def register_recovery_hook(self, hook: Callable):
        """Register custom recovery hook"""
        self.recovery_hooks.append(hook)

    def register_performance_hook(self, hook: Callable):
        """Register custom performance hook"""
        self.performance_hooks.append(hook)
