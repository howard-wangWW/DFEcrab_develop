"""
ASR拼音纠错技能 (asr_corrector)

纠正ASR识别错误的文本，核心逻辑：
1. 纯拼音匹配：将ASR文本分词后转拼音，与正确词汇表的拼音比对
   - 任何同音字错误都能被纠正，不需要预知错误模式
2. 模型兜底：拼音匹配无法覆盖时，调用LLM进行语义纠错

设计原则：
- ASR输出不可预测，不依赖硬编码错误映射表
- 基于拼音的通用性：只要拼音相同就能匹配
- 支持单字、双字、三字、四字滑动窗口
"""

import json
import re
from typing import Dict, List, Optional, Tuple

SKILL_METADATA = {
    "name": "asr_corrector",
    "description": "纠正ASR语音识别错误的文本。基于拼音匹配纠正同音字错误，匹配失败时调用模型纠错。",
    "parameters": {
        "text": {
            "type": "string",
            "description": "ASR识别的原始文本"
        },
        "use_model": {
            "type": "boolean",
            "description": "拼音匹配失败时是否使用模型兜底（默认true）",
            "default": True
        }
    }
}

# 电力调度专业正确词汇表（按拼音匹配）
# 这些词汇的拼音会被预建索引，用于匹配ASR输出中的同音字错误
CORRECT_VOCABULARY = [
    # 核心业务术语
    "重过载", "重载", "保供电", "受令资格", "跳闸", "异常信号",
    "早会材料", "城区一小时", "理论题", "操作票", "调度", "调度员",
    "合环转供电", "图实不符", "安全措施", "人身伤害", "事故事件",
    "反措", "保命", "危险点", "应急", "教育培训",
    "配网调度", "调度纪律", "五必核一确认", "三核对",
    "供电局", "分局", "供电所",
    "西山局", "官渡局", "五华局", "盘龙局", "呈贡局",
    "设备", "线路", "开关", "刀闸", "变压器",
    "停电", "送电", "检修", "抢修", "操作",
    "运行", "维护", "管理", "规程", "制度",
    "负荷", "电流", "电压", "功率", "电量",
    "故障", "事故", "缺陷", "隐患", "异常",
    "处理", "排查", "分析", "统计", "汇总",
    "今天", "昨天", "明天", "上午", "下午",
    "查询", "统计", "汇总", "排名", "列表",
    "跳闸统计", "重过载", "过载", "重载",
    "受令", "下令", "停送电", "倒闸操作",
    "安全", "措施", "工作票", "操作票",
    "接地", "验电", "挂牌", "上锁",
    "交接", "值班", "调度", "监控",
    "计划", "安排", "通知", "公告",
]


def _get_pinyin(text: str) -> str:
    """获取文本的拼音（不带声调，去除空格）"""
    try:
        from pypinyin import lazy_pinyin
        return "".join(lazy_pinyin(text))
    except ImportError:
        return text


def _build_pinyin_index() -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    构建拼音索引表
    
    Returns:
        - py_to_word: 拼音 → 正确词汇 的映射
        - py_lengths: 按拼音长度分组的词汇
    """
    py_to_word = {}
    for word in CORRECT_VOCABULARY:
        py = _get_pinyin(word)
        py_to_word[py] = word
    return py_to_word, {}


# 预构建拼音索引
PINYIN_TO_WORD, _ = _build_pinyin_index()

# 预计算每个正确词汇的拼音
CORRECT_WORDS_PINYIN = {word: _get_pinyin(word) for word in CORRECT_VOCABULARY}

# 按拼音长度分组（用于快速查找）
BY_PINYIN_LENGTH: Dict[int, List[Tuple[str, str]]] = {}
for word, py in CORRECT_WORDS_PINYIN.items():
    py_len = len(py)
    if py_len not in BY_PINYIN_LENGTH:
        BY_PINYIN_LENGTH[py_len] = []
    BY_PINYIN_LENGTH[py_len].append((py, word))


def _find_best_pinyin_match(segment_pinyin: str, segment_text: str) -> Optional[Tuple[str, int]]:
    """
    查找拼音匹配的最佳结果
    
    仅使用完全匹配（最可靠的方式）：
    拼音完全相同但文字不同 → 肯定是ASR同音字错误
    
    Returns:
        (正确词汇, 匹配类型) 或 None
    """
    py_len = len(segment_pinyin)
    if py_len in BY_PINYIN_LENGTH:
        for correct_py, correct_word in BY_PINYIN_LENGTH[py_len]:
            if segment_pinyin == correct_py and segment_text != correct_word:
                return (correct_word, "exact")
    
    return None


def _correct_by_pinyin(text: str) -> Tuple[str, List[Dict]]:
    """
    基于拼音的纠错核心算法
    
    策略：
    1. 从左到右滑动窗口（按字符数取窗口）
    2. 窗口从大到小尝试（优先长匹配）
    3. 使用多级拼音匹配（完全匹配→前缀匹配→子串匹配）
    4. 找到匹配则替换，跳过已纠正的区域
    
    Returns:
        (纠正后的文本, 纠正记录列表)
    """
    corrections = []
    result = text
    
    i = 0
    while i < len(result):
        best_match = None
        best_match_type = None
        best_window_size = 0
        
        # 尝试不同大小的窗口，优先大窗口
        for window_size in range(min(8, len(result) - i), 0, -1):
            segment = result[i:i + window_size]
            
            # 跳过无中文的片段
            if not re.search(r'[\u4e00-\u9fff]', segment):
                continue
            
            segment_pinyin = _get_pinyin(segment)
            if len(segment_pinyin) < 2:
                continue
            
            match_result = _find_best_pinyin_match(segment_pinyin, segment)
            
            if match_result:
                matched_word, match_type = match_result
                # 确保这是最佳匹配（匹配到的词更长或窗口更大）
                if best_match is None or len(matched_word) >= len(best_match):
                    best_match = matched_word
                    best_match_type = match_type
                    best_window_size = window_size
                break  # 找到匹配就跳出窗口循环
        
        if best_match:
            # 执行纠正：用正确词汇替换原窗口
            old_text = result[i:i + best_window_size]
            result = result[:i] + best_match + result[i + best_window_size:]
            corrections.append({
                "original": old_text,
                "corrected": best_match,
                "method": f"pinyin_{best_match_type}",
                "pinyin": _get_pinyin(best_match)
            })
            # 跳转到纠正后词汇的末尾
            i += len(best_match)
        else:
            i += 1
    
    return result, corrections


def _correct_by_model(text: str) -> Tuple[str, List[Dict]]:
    """
    通过LLM模型纠正
    
    当拼音匹配无法识别时使用，利用模型的语义理解能力纠错。
    """
    try:
        import httpx
        import os
        
        # 从配置文件读取模型配置
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "dfecrab.json"
        )
        
        api_base = "http://172.20.41.86:8124/v1"
        model_name = "Qwen3-14B-HGY"
        
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # ★ 模型统一在 model_providers 段：取第一个 enabled（顶层 model 段已移除）
                for prov_name, prov_cfg in config.get("model_providers", {}).items():
                    if prov_cfg.get("enabled", False) and prov_cfg.get("model_name"):
                        api_base = prov_cfg["api_base"]
                        model_name = prov_cfg["model_name"]
                        break
        
        system_prompt = "你是电力调度领域的ASR语音识别纠错专家。用户输入是语音识别生成的文本，其中包含大量同音错别字。请纠正为正确的电力调度专业术语，直接输出纠正后的文本，不要添加任何解释。"
        
        examples = """
常见错误示例（仅供参考，实际错误形式多样）：
- "重过灾/重过仔/种过宰/中过载" → "重过载"
- "保供点/宝供电/保公电/报供电" → "保供电"  
- "受令格/受令隔/授令资格" → "受令资格"
- "跳扎/跳炸/挑闸" → "跳闸"
- "早会裁了/早会裁料" → "早会材料"
- "异常信好/异常新号" → "异常信号"
- "理论提/理论替" → "理论题"
- "操作漂/操作飘" → "操作票"
- "掉度" → "调度"
- "合还转供电" → "合环转供电"
- "图实不付" → "图实不符"
- "安全错施" → "安全措施"
- "人生伤害" → "人身伤害"
- "事故实践" → "事故事件"
"""
        
        user_prompt = f"""请纠正以下ASR识别文本中的同音错别字：

{examples}

需要纠正的文本：
{text}

纠正后的文本："""

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
            "stream": False
        }
        
        url = f"{api_base}/chat/completions"
        
        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            
            corrected_text = result["choices"][0]["message"]["content"].strip()

            # 清理 <think>...</think> 标签（Qwen3 模型会自动添加推理标签）
            corrected_text = re.sub(r'<think>[\s\S]*?</think>', '', corrected_text, flags=re.IGNORECASE).strip()
            # 清理单独的 <think> 或 </think> 标签
            corrected_text = re.sub(r'</?think>', '', corrected_text, flags=re.IGNORECASE).strip()

            # 清理可能的markdown格式
            if corrected_text.startswith("```"):
                corrected_text = re.sub(r'^```.*?\n', '', corrected_text)
                corrected_text = re.sub(r'\n```$', '', corrected_text)
            
            if corrected_text and corrected_text != text:
                return corrected_text, [{
                    "original": text,
                    "corrected": corrected_text,
                    "method": "model"
                }]
            else:
                return text, []
                
    except Exception as e:
        return text, [{
            "original": text,
            "corrected": text,
            "method": "model_failed",
            "error": str(e)
        }]


def execute(text: str = "", use_model: bool = True, **kwargs) -> Dict:
    """
    ASR拼音纠错主函数
    
    流程：
    1. 先拼音匹配纠正同音字（快速，<100ms）
    2. 如果拼音完全没纠正任何内容 → 模型兜底
       （如果拼音已经纠正了，说明文本大部分正确，不再调用模型）
    
    Args:
        text: ASR识别的原始文本
        use_model: 拼音匹配完全失败时是否使用模型兜底
        
    Returns:
        包含纠正结果的字典
    """
    if not text or not text.strip():
        return {
            "status": "error",
            "message": "输入文本为空"
        }
    
    original_text = text
    all_corrections = []
    
    # 第一层：纯拼音匹配（快速纠正同音字）
    text, corrections = _correct_by_pinyin(text)
    all_corrections.extend(corrections)
    
    # 第二层：只有拼音完全没纠正时才用模型兜底
    if use_model and not all_corrections:
        text, model_corrections = _correct_by_model(text)
        if model_corrections:
            all_corrections.extend(model_corrections)
    
    return {
        "status": "success",
        "original_text": original_text,
        "corrected_text": text,
        "has_correction": len(all_corrections) > 0 and text != original_text,
        "corrections": all_corrections,
        "correction_count": len(all_corrections)
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="ASR拼音纠错技能")
    parser.add_argument("--text", "-t", default="", help="ASR识别的原始文本")
    parser.add_argument("--no-model", action="store_true", help="不使用模型兜底")
    args = parser.parse_args()
    
    result = execute(text=args.text, use_model=not args.no_model)
    print(json.dumps(result, ensure_ascii=False, indent=2))