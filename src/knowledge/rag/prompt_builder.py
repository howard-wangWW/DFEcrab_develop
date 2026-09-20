# src/knowledge/rag/prompt_builder.py
"""
Prompt构建器
"""
from typing import Dict, Optional


class PromptBuilder:
    """Prompt构建器"""
    
    def __init__(self, system_prompt: Optional[str] = None):
        self.system_prompt = system_prompt or self._default_system_prompt()
    
    def _default_system_prompt(self) -> str:
        return """你是电网运维专业知识助手，专注于电力调度、配网运维、安全规程等领域。

【你的能力】
1. 基于提供的参考资料准确回答问题
2. 对专业术语和概念给出清晰解释
3. 如果信息不足，明确告知用户

【回答要求】
1. 只基于参考资料回答，不编造信息
2. 引用资料时标注来源
3. 回答要专业、准确、有条理
4. 如果问题涉及多个方面，分类回答
5. 只回答参考资料中明确提到的内容，不要输出「资料未提及」「推测」「估计」等发散章节
6. 回答控制在 800 字以内，用简洁条目，不要过度展开

【格式要求】
- 使用清晰的分点或段落
- 专业术语保持原样
- 数据引用要准确"""
    
    def build_qa_prompt(self, question: str, context: str) -> str:
        """构建问答Prompt"""
        return f"""{self.system_prompt}

【参考资料】
{context}

【用户问题】
{question}

请基于以上参考资料回答用户问题。如果参考资料中没有相关信息，请直接说明，不要自行推测或添加资料外内容。"""
    
    def build_summary_prompt(self, context: str, max_length: int = 500) -> str:
        """构建摘要Prompt"""
        return f"""请用 {max_length} 字以内总结以下内容：

{context}

总结要求：
1. 保留关键信息
2. 语言简洁
3. 突出要点"""
    
    def build_chat_prompt(self, question: str, context: str, history: list = None) -> str:
        """构建对话Prompt（包含历史）"""
        prompt = self.build_qa_prompt(question, context)
        
        if history:
            history_text = "\n".join([
                f"用户: {h['question']}\n助手: {h['answer']}"
                for h in history[-3:]  # 只保留最近3轮
            ])
            prompt = f"【对话历史】\n{history_text}\n\n{prompt}"
        
        return prompt
