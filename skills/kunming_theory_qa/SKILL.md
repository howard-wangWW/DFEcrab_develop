---
name: "kunming_theory_qa"
description: "检索昆明配网理论题本地问答库。Invoke when the query is a theory question, short-answer item, or did not match existing Kunming business APIs."
---

# 昆明理论题问答检索

## 用途
用于检索本地维护的昆明配网理论题问答库，按题号或语义相似度返回对应答案。

## 触发场景
- 用户提问属于理论题、简答题、知识问答
- 用户直接说“第X题”
- 未命中现有业务分类（跳闸、早会、受令资格、异常信号、重过载等）时

## 输入要求
- `query`：用户原始问题
- `top_k`：可选，返回候选数量
- `min_score`：可选，最低相似度阈值

## 输出要求
返回 JSON，至少包含：
- `status`
- `hit`
- `candidates`

其中 `hit.answer` 为最终回答内容。
