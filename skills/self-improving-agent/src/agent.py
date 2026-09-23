"""
Self-Improving Agent Module
Main agent class for self-improving system
"""

from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import time

from src.memory import LearningMemory
from src.hooks import HookManager


class SelfImprovingAgent:
    """Self-improving agent that learns from interactions"""

    def __init__(self, workspace: Optional[Path] = None):
        """Initialize self-improving agent"""
        if workspace is None:
            workspace = Path.home() / '.openclaw' / 'workspace'

        self.workspace = Path(workspace)
        self.memory = LearningMemory(workspace)
        self.hooks = HookManager(workspace)

        # Current session tracking
        self.session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.session_start = None
        self.interaction_count = 0
        self.success_patterns: List[str] = []

    def start_session(self):
        """Start a new session"""
        self.session_start = time.time()
        self.interaction_count = 0
        self.success_patterns = []
        print(f"📊 Session started: {self.session_id}")

    def end_session(self):
        """End current session and learn from it"""
        if self.session_start is None:
            print("⚠️  No active session to end")
            return

        duration = int(time.time() - self.session_start)

        session_data = {
            'id': self.session_id,
            'duration': duration,
            'interactions': self.interaction_count,
            'success_patterns': self.success_patterns
        }

        self.hooks.on_session_end(session_data)

        print(f"✅ Session ended: {self.session_id}")
        print(f"   Duration: {duration}s, Interactions: {self.interaction_count}")

        self.session_start = None

    def log_error(self, error_type: str, error_message: str, context: Optional[Dict] = None):
        """Log an error for learning"""
        error_data = {
            'type': error_type,
            'message': error_message,
            'context': context or {}
        }
        self.hooks.on_error(error_data)
        print(f"❌ Error logged: {error_type}")

    def log_recovery(self, recovery_method: str, context: Optional[Dict] = None):
        """Log a successful recovery for learning"""
        recovery_data = {
            'method': recovery_method,
            'context': context or {}
        }
        self.hooks.on_recovery(recovery_data)
        print(f"✅ Recovery logged: {recovery_method}")
        self.success_patterns.append(f"recovery_{recovery_method}")

    def log_performance(self, metric_type: str, metric_value: float,
                        context: Optional[Dict] = None, optimizations: Optional[List[str]] = None):
        """Log a performance metric for learning"""
        metric_data = {
            'type': metric_type,
            'value': metric_value,
            'context': context or {},
            'optimizations': optimizations or []
        }
        self.hooks.on_performance(metric_data)
        print(f"📈 Performance logged: {metric_type} = {metric_value}")

    def track_interaction(self, success: bool = True):
        """Track an interaction"""
        self.interaction_count += 1
        if success:
            self.success_patterns.append("successful_interaction")

    def extract_learnings(self) -> List[Dict]:
        """Extract learnings from current session"""
        learnings = []

        if self.success_patterns:
            learnings.append({
                'category': 'session',
                'data': {
                    'session_id': self.session_id,
                    'duration': int(time.time() - self.session_start) if self.session_start else 0,
                    'interactions': self.interaction_count,
                    'success_patterns': self.success_patterns
                }
            })

        return learnings

    def get_learnings(self) -> List[Dict]:
        """Get all stored learnings"""
        return self.memory.get_all()

    def review_learnings(self):
        """Review all learnings"""
        learnings = self.get_learnings()
        print(f"\n📖 Total learnings: {len(learnings)}")

        for i, learning in enumerate(learnings[:10], 1):  # Show first 10
            print(f"\n{i}. [{learning['category'].upper()}] {learning['title']}")
            print(f"   {learning['date']}")

    def run(self):
        """Run the agent (main loop placeholder)"""
        print("🧤 Self-Improving Agent running...")
        print("   Use hooks to capture learnings")
        # This is a placeholder - actual implementation would interact
        # with the agent framework
