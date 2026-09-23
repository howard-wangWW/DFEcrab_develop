"""
Learning Memory Module
Stores and retrieves learnings from interactions
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class LearningMemory:
    """Learning memory storage system"""

    def __init__(self, workspace: Optional[Path] = None):
        """Initialize learning memory"""
        if workspace is None:
            workspace = Path.home() / '.openclaw' / 'workspace'

        self.workspace = Path(workspace)
        self.learnings_dir = self.workspace / 'learnings'
        self.learnings_dir.mkdir(parents=True, exist_ok=True)

        # Learning file paths
        self.sessions_file = self.learnings_dir / 'sessions.json'
        self.errors_file = self.learnings_dir / 'errors.json'
        self.recoveries_file = self.learnings_dir / 'recoveries.json'
        self.performance_file = self.learnings_dir / 'performance.json'

        # Load learnings
        self.sessions = self._load_json(self.sessions_file, [])
        self.errors = self._load_json(self.errors_file, [])
        self.recoveries = self._load_json(self.recoveries_file, [])
        self.performance = self._load_json(self.performance_file, [])

    def _load_json(self, file_path: Path, default):
        """Load JSON file"""
        if file_path.exists():
            try:
                return json.loads(file_path.read_text(encoding='utf-8'))
            except Exception as e:
                print(f"⚠️  Loading {file_path.name} failed: {e}")
                return default
        return default

    def _save_json(self, file_path: Path, data):
        """Save JSON file"""
        try:
            file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            print(f"⚠️  Saving {file_path.name} failed: {e}")

    def store_session(self, session_id: str, duration: int, interactions: int,
                      success_patterns: List[str]):
        """Store session learning"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
            "duration": duration,
            "interactions": interactions,
            "success_patterns": success_patterns
        }
        self.sessions.append(entry)
        self._save_json(self.sessions_file, self.sessions)

    def store_error(self, error_type: str, error_message: str, context: Dict):
        """Store error learning"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "error_type": error_type,
            "error_message": error_message,
            "context": context
        }
        self.errors.append(entry)
        self._save_json(self.errors_file, self.errors)

    def store_recovery(self, recovery_method: str, context: Dict):
        """Store recovery learning"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "recovery_method": recovery_method,
            "context": context
        }
        self.recoveries.append(entry)
        self._save_json(self.recoveries_file, self.recoveries)

    def store_performance(self, metric_type: str, metric_value: float,
                         context: Dict, optimizations: List[str]):
        """Store performance learning"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "metric_type": metric_type,
            "metric_value": metric_value,
            "context": context,
            "optimizations": optimizations
        }
        self.performance.append(entry)
        self._save_json(self.performance_file, self.performance)

    def store(self, learnings: List[Dict]):
        """Store multiple learnings"""
        for learning in learnings:
            category = learning.get('category')
            data = learning.get('data', {})

            if category == 'session':
                self.store_session(
                    data.get('session_id', ''),
                    data.get('duration', 0),
                    data.get('interactions', 0),
                    data.get('success_patterns', [])
                )
            elif category == 'error':
                self.store_error(
                    data.get('error_type', ''),
                    data.get('error_message', ''),
                    data.get('context', {})
                )
            elif category == 'recovery':
                self.store_recovery(
                    data.get('recovery_method', ''),
                    data.get('context', {})
                )
            elif category == 'performance':
                self.store_performance(
                    data.get('metric_type', ''),
                    data.get('metric_value', 0),
                    data.get('context', {}),
                    data.get('optimizations', [])
                )

    def get_all(self) -> List[Dict]:
        """Get all learnings"""
        all_learnings = []

        for entry in self.sessions:
            all_learnings.append({
                'title': f"Session {entry.get('session_id', '')}",
                'category': 'session',
                'date': entry.get('timestamp', ''),
                'content': entry
            })

        for entry in self.errors:
            all_learnings.append({
                'title': f"Error: {entry.get('error_type', '')}",
                'category': 'error',
                'date': entry.get('timestamp', ''),
                'content': entry
            })

        for entry in self.recoveries:
            all_learnings.append({
                'title': f"Recovery: {entry.get('recovery_method', '')}",
                'category': 'recovery',
                'date': entry.get('timestamp', ''),
                'content': entry
            })

        for entry in self.performance:
            all_learnings.append({
                'title': f"Performance: {entry.get('metric_type', '')}",
                'category': 'performance',
                'date': entry.get('timestamp', ''),
                'content': entry
            })

        return sorted(all_learnings, key=lambda x: x['date'], reverse=True)

    def export(self, output_file: Path):
        """Export learnings to markdown file"""
        learnings = self.get_all()

        content = "# Self-Improving Agent Learnings\n\n"
        content += f"Generated: {datetime.now().isoformat()}\n\n"
        content += f"Total Learnings: {len(learnings)}\n\n"

        for category in ['session', 'error', 'recovery', 'performance']:
            category_learnings = [l for l in learnings if l['category'] == category]
            if category_learnings:
                content += f"## {category.title()} Learnings ({len(category_learnings)})\n\n"
                for learning in category_learnings:
                    content += f"### {learning['title']}\n"
                    content += f"**Date**: {learning['date']}\n\n"
                    content += f"```json\n{json.dumps(learning['content'], indent=2, ensure_ascii=False)}\n```\n\n"

        output_file.write_text(content, encoding='utf-8')

    def load(self):
        """Reload all learnings from files"""
        self.sessions = self._load_json(self.sessions_file, [])
        self.errors = self._load_json(self.errors_file, [])
        self.recoveries = self._load_json(self.recoveries_file, [])
        self.performance = self._load_json(self.performance_file, [])
