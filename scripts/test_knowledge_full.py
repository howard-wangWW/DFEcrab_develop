#!/usr/bin/env python3
"""
知识库完整测试脚本
"""
import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge.skills.knowledge_qa import KnowledgeQASkill
from src.knowledge.storage.document_repo import DocumentRepository


def print_separator(char="=", length=60):
    print(char * length)


def test_knowledge_base():
    """测试知识库"""
    
    print_separator()
    print("🧪 知识库完整测试")
    print_separator()
    
    # 1. 检查文档
    print("\n📄 1. 检查文档:")
    repo = DocumentRepository()
    docs = repo.list_documents()
    print(f"   文档总数: {len(docs)}")
    for doc in docs:
        print(f"   - [{doc.status}] {doc.title} ({doc.category}) - {doc.chunk_count}个切片")
    
    # 2. 检查索引
    print("\n🗂️ 2. 检查索引:")
    stats = repo.get_stats()
    print(f"   总切片数: {stats['total_chunks']}")
    print(f"   分类统计: {json.dumps(stats['by_category'], ensure_ascii=False)}")
    
    # 3. 初始化技能
    print("\n🤖 3. 初始化知识库技能:")
    skill = KnowledgeQASkill()
    if skill.is_ready():
        print("   ✅ 知识库技能就绪")
    else:
        print("   ❌ 知识库技能未就绪")
        return
    
    # 4. 测试问答
    print("\n❓ 4. 测试问答:")
    
    test_questions = [
        "倒闸操作的要求有哪些？",
        "什么是两票三制？",
        "调度纪律有什么要求？",
        "合环转供电怎么操作？",
        "事故处理的原则是什么？",
        "五必核一确认是什么？",
        "值班员的职责有哪些？",
        "设备巡视检查要点是什么？",
        "安全措施有什么要求？",
        "电网调度常用术语有哪些？",
    ]
    
    success_count = 0
    for i, question in enumerate(test_questions, 1):
        print(f"\n   [{i}] 问题: {question}")
        result = skill.execute(question, top_k=3)
        
        if result["status"] == "success":
            success_count += 1
            answer = result["answer"]
            # 截断显示
            lines = answer.split('\n')[:8]
            preview = '\n'.join(lines)
            if len(answer) > 300:
                preview += "\n   ..."
            print(f"   回答: {preview}")
            print(f"   来源数: {result.get('total_sources', 0)}")
        else:
            print(f"   ❌ 错误: {result.get('message')}")
    
    # 5. 测试统计
    print_separator()
    print("📊 测试结果:")
    print(f"   成功: {success_count}/{len(test_questions)}")
    
    # 6. 测试搜索特定关键词
    print_separator()
    print("🔍 5. 关键词搜索测试:")
    
    keywords = ["倒闸", "保护", "调度", "安全", "事故"]
    for keyword in keywords:
        result = skill.execute(keyword, top_k=2)
        if result["status"] == "success" and result["sources"]:
            print(f"   ✅ '{keyword}' 找到 {len(result['sources'])} 条结果")
        else:
            print(f"   ❌ '{keyword}' 未找到结果")
    
    print_separator()
    print("✅ 测试完成!")
    print_separator()


if __name__ == "__main__":
    test_knowledge_base()
