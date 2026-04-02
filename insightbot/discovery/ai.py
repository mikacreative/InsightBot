"""
AI 推荐策略：调用大语言模型推荐长尾 RSS 源
"""

import json
import logging
import re
from typing import List, Optional

from insightbot.discovery.base import DiscoveryStrategy

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_TEMPLATE = """你是一个资深的 RSS 订阅源推荐专家。请根据以下板块信息，推荐优质的中文 RSS 订阅源。

板块信息：{category_info}

要求：
1. 推荐真正有价值的、持续更新的 RSS 源
2. 每个推荐需提供：RSS 源 URL、推荐理由、预估质量（high/medium/low）
3. 必须返回至少 5 个推荐
4. 只返回你知道确实存在的 RSS 源，不要编造
5. 优先推荐独立的博客、垂直网站，专业媒体的 RSS 源

请以 JSON 数组格式返回，格式如下：
[
  {
    "feed_url": "https://example.com/feed",
    "reason": "推荐理由",
    "estimated_quality": "high"
  },
  ...
]

只返回 JSON，不要其他内容。"""


class AIStrategy(DiscoveryStrategy):
    """
    AI 推荐策略
    调用大语言模型，基于板块信息推荐长尾 RSS 源。
    """

    def __init__(
        self,
        api_url: str = "",
        api_key: str = "",
        model: str = "gpt-4o-mini",
        prompt_template: Optional[str] = None,
        max_recommendations: int = 10,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.prompt_template = prompt_template or DEFAULT_PROMPT_TEMPLATE
        self.max_recommendations = max_recommendations

    @property
    def strategy_name(self) -> str:
        return "ai"

    def _get_chat_completion(self):
        """获取 chat_completion 函数"""
        try:
            from insightbot.ai import chat_completion
            return chat_completion
        except ImportError:
            try:
                from insightbot.ai import chat_completion as cc
                return cc
            except ImportError:
                logger.warning("[AIStrategy] chat_completion not found. AI discovery will be skipped.")
                return None

    def _call_ai(self, prompt: str) -> str:
        """调用 AI 返回文本"""
        chat_fn = self._get_chat_completion()
        if not chat_fn:
            return ""

        # 从 config.json 读取 AI 配置
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
            api_url = self.api_url or config.get("ai", {}).get("api_url", "")
            api_key = self.api_key or config.get("ai", {}).get("api_key", "")
            model = config.get("ai", {}).get("model", self.model)
        except Exception:
            api_url = self.api_url
            api_key = self.api_key
            model = self.model

        if not api_url or not api_key:
            logger.warning("[AIStrategy] AI API credentials not configured")
            return ""

        try:
            result = chat_fn(
                api_url=api_url,
                api_key=api_key,
                model=model,
                system_prompt="你是一个资深的 RSS 订阅源推荐专家。",
                user_text=prompt,
                temperature=0.8,
                timeout_s=60,
            )
            return result
        except Exception as e:
            logger.warning(f"[AIStrategy] AI call failed: {e}")
            return ""

    def _parse_json_response(self, text: str) -> List[dict]:
        """从响应中解析 JSON"""
        # 尝试提取 JSON 代码块
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            text = match.group(1)

        try:
            data = json.loads(text.strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 数组
        array_match = re.search(r"\[\s*\{[\s\S]+\}\s*\]", text)
        if array_match:
            try:
                return json.loads(array_match.group(0))
            except json.JSONDecodeError:
                pass

        return []

    def discover(
        self, keywords: List[str], existing_urls: List[str]
    ) -> List[dict]:
        """通过 AI 推荐 RSS 源"""
        category_info = "、".join(keywords) if keywords else "综合"
        prompt = self.prompt_template.format(category_info=category_info)

        logger.info(f"[AIStrategy] Requesting AI recommendations for: {category_info}")
        response = self._call_ai(prompt)
        if not response:
            return []

        recommendations = self._parse_json_response(response)
        feeds = []
        for rec in recommendations[: self.max_recommendations]:
            feed_url = rec.get("feed_url", "")
            if not feed_url or not feed_url.startswith("http"):
                continue

            feeds.append({
                "feed_url": feed_url,
                "discovery_query": "|".join(keywords),
                "source_strategy": self.strategy_name,
                "reason": rec.get("reason", "AI 推荐"),
                "estimated_quality": rec.get("estimated_quality", "medium"),
            })

        logger.info(f"[AIStrategy] Got {len(feeds)} AI recommendations")
        return feeds
