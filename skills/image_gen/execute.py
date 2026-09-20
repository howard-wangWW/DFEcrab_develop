"""
图片生成技能：根据文本描述（prompt）调用图片模型生成图片并落盘。

依赖配置：config/dfecrab.json 的 image_providers / image_generation 段。
"""

# ★ 返回 dict，不要返回 json.dumps 的字符串：
#   ReAct 循环（loop.py:1324）会把技能返回值再 json.dumps 一次后回填给 LLM，
#   这里返回 str 会被二次转义成 "{\"success\": true, ...}"，模型会读错格式。


def execute(prompt: str, size: str = "1024x1024", n: int = 1, provider: str = "") -> dict:
    """根据文本描述生成图片，返回可访问的图片地址

    Args:
        prompt: 图片描述（越具体越好，如"一只在草地上奔跑的柯基犬，写实风格，柔和晨光"）
        size: 图片尺寸，可选 512x512 / 768x768 / 1024x1024 / 1024x1536 / 1536x1024
        n: 生成张数，默认 1，最大 4
        provider: 指定图片服务（config/dfecrab.json 中 image_providers 的 key），留空用默认

    Returns:
        dict：包含图片 id 与可访问 URL；失败时包含 error 说明
    """
    from src.monitoring.usage_store import current_usage_context
    from src.services.image_service import ImageProviderError, get_image_service

    prompt = (prompt or "").strip()
    if not prompt:
        return {"success": False, "error": "缺少参数 prompt（图片描述）"}

    ctx = current_usage_context()
    try:
        result = get_image_service().generate(
            prompt=prompt,
            size=(size or "").strip() or None,
            n=n,
            provider=(provider or "").strip() or None,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
        )
    except ImageProviderError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"图片生成失败: {exc}"}

    images = [
        {"image_id": item["image_id"], "url": item["url"]}
        for item in result.get("images", [])
    ]
    first = images[0]["url"] if images else ""
    return {
        "success": True,
        "count": result.get("count", len(images)),
        "size": result.get("size", ""),
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
        "images": images,
        "display": f"![{prompt[:30]}]({first})" if first else "",
        "hint": "请用 Markdown 图片语法把每张图展示给用户（一行一张），不要把图片数据原样输出",
    }
