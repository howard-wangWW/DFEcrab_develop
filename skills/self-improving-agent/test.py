#!/usr/bin/env python3
"""
Test script for self-improving-agent
"""

import sys
from pathlib import Path

# Add skill directory to path
skill_dir = Path(__file__).parent
sys.path.insert(0, str(skill_dir))

from src.agent import SelfImprovingAgent
from src.hooks import HookManager
from src.memory import LearningMemory


def test_agent():
    """Test self-improving agent"""
    print("🧪 Testing Self-Improving Agent\n")

    # Use DFEcrab workspace for testing
    workspace = Path("/Users/zhanghanzhi/workspace/DFEcrab")

    # Initialize components
    print("📦 Initializing components...")
    agent = SelfImprovingAgent(workspace)
    hooks = HookManager(workspace)
    memory = LearningMemory(workspace)

    # Test session tracking
    print("\n📊 Testing session tracking...")
    agent.start_session()
    agent.track_interaction(success=True)
    agent.track_interaction(success=True)
    agent.end_session()

    # Test error learning
    print("\n❌ Testing error learning...")
    agent.log_error(
        error_type="ValueError",
        error_message="Invalid parameter",
        context={"param": "age", "value": -1}
    )

    # Test recovery learning
    print("\n✅ Testing recovery learning...")
    agent.log_recovery(
        recovery_method="validation_check",
        context={"action": "added validation for age parameter"}
    )

    # Test performance learning
    print("\n📈 Testing performance learning...")
    agent.log_performance(
        metric_type="response_time",
        metric_value=150,
        context={"operation": "query"},
        optimizations=["Add caching", "Optimize query"]
    )

    # Review learnings
    print("\n📖 Reviewing all learnings...")
    agent.review_learnings()

    # Export learnings
    print("\n📤 Exporting learnings...")
    output_file = workspace / "learnings_export.md"
    memory.export(output_file)
    print(f"✅ Exported to {output_file}")

    print("\n✅ All tests completed successfully!")


if __name__ == "__main__":
    test_agent()
