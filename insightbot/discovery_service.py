"""
核心发现调度服务 DiscoveryService
- 管理 recommended_feeds 的增删查改
- 池满暂停/恢复逻辑（pool_max=20, resume_after_processed=5）
- run_discovery(): 运行所有策略，返回新增数量
- get_pending_feeds(): 返回待处理列表
- approve(url, category): 从 recommended_feeds 移到 feeds
- reject(url): 从 recommended_feeds 删除
- refresh_pool(): 换一批（从 pending 里随机返回部分）
"""

import json
import logging
import random
from datetime import datetime
from typing import List, Optional, Dict

from insightbot.discovery.directory import DirectoryStrategy
from insightbot.discovery.search import SearchStrategy
from insightbot.discovery.ai import AIStrategy
from insightbot.discovery.dedup import Deduplicator
from insightbot.discovery.quality import QualityScorer

logger = logging.getLogger(__name__)

DEFAULT_DISCOVERY_CONFIG = {
    "enabled": True,
    "pool_max": 20,
    "resume_after_processed": 5,
    "strategies": ["directory", "search", "ai"],
    "keywords": ["营销", "科技", "AI", "产品", "设计"],
}


class DiscoveryService:
    """
    订阅源发现服务
    职责：
    1. 加载和管理 discovery_config / recommended_feeds
    2. 运行发现策略（目录/搜索/AI）
    3. 三层去重 + 质量评估
    4. 管理推荐池（增删查改）
    5. 与主配置文件（config.json）交互
    """

    def __init__(
        self,
        config_path: str = "config.json",
        discovery_config: Optional[dict] = None,
    ):
        self.config_path = config_path
        self.config: dict = self._load_config()

        if discovery_config:
            self.discovery_config = discovery_config
        else:
            self.discovery_config = self.config.get(
                "discovery_config", DEFAULT_DISCOVERY_CONFIG.copy()
            )

        self.recommended_feeds: List[dict] = self.config.get("recommended_feeds", [])

        # 加载已有 feeds（用于去重）
        existing_feeds = self.config.get("feeds", {})
        if isinstance(existing_feeds, dict):
            all_feeds = []
            for feeds_list in existing_feeds.values():
                all_feeds.extend(feeds_list)
            self.existing_feeds = all_feeds
        elif isinstance(existing_feeds, list):
            self.existing_feeds = existing_feeds
        else:
            self.existing_feeds = []

        self.pool_max = self.discovery_config.get("pool_max", 20)
        self.resume_after = self.discovery_config.get("resume_after_processed", 5)
        self.strategies = self.discovery_config.get("strategies", ["directory", "search", "ai"])
        self.keywords = self.discovery_config.get("keywords", ["营销", "科技"])

        self._strategy_instances: Dict[str, object] = {}
        self._quality_scorer: Optional[QualityScorer] = None

    def _load_config(self) -> dict:
        """加载配置文件"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"[DiscoveryService] Config not found: {self.config_path}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"[DiscoveryService] Invalid JSON in config: {e}")
            return {}

    def _save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[DiscoveryService] Failed to save config: {e}")

    def _get_strategy(self, name: str):
        """获取或创建策略实例"""
        if name not in self._strategy_instances:
            if name == "directory":
                self._strategy_instances[name] = DirectoryStrategy()
            elif name == "search":
                self._strategy_instances[name] = SearchStrategy()
            elif name == "ai":
                self._strategy_instances[name] = AIStrategy()
            else:
                return None
        return self._strategy_instances[name]

    @property
    def quality_scorer(self) -> QualityScorer:
        """获取或创建质量评分器"""
        if self._quality_scorer is None:
            self._quality_scorer = QualityScorer()
        return self._quality_scorer

    @property
    def pending_count(self) -> int:
        """当前待处理推荐数量"""
        return len([f for f in self.recommended_feeds if f.get("status") == "pending"])

    @property
    def is_pool_full(self) -> bool:
        """推荐池是否已满"""
        return self.pending_count >= self.pool_max

    @property
    def is_paused(self) -> bool:
        """是否因池满而暂停发现"""
        if not self.is_pool_full:
            return False
        processed = sum(
            1 for f in self.recommended_feeds
            if f.get("status") in ("approved", "rejected")
        )
        return processed < self.resume_after

    def _get_existing_urls(self) -> List[str]:
        """获取所有已存在 URL（feeds + recommended_feeds）"""
        urls = []
        for feed in self.existing_feeds:
            url = feed.get("feed_url", "")
            if url:
                urls.append(url)
        for feed in self.recommended_feeds:
            url = feed.get("feed_url", "")
            if url:
                urls.append(url)
        return urls

    def _deduplicate_feeds(self, feeds: List[dict]) -> List[dict]:
        """对发现的 feeds 执行三层去重"""
        all_existing = self.existing_feeds + [
            {"feed_url": url} for url in self._get_existing_urls()
        ]
        deduplicator = Deduplicator(all_existing)
        feeds = deduplicator.deduplicate(feeds)
        return feeds

    def _assess_quality(self, feeds: List[dict]) -> List[dict]:
        """评估 feeds 质量"""
        urls = [f["feed_url"] for f in feeds]
        quality_map = self.quality_scorer.assess_quality_batch(urls)
        for feed in feeds:
            url = feed["feed_url"]
            if "estimated_quality" not in feed:
                feed["estimated_quality"] = quality_map.get(url, "low")
        return feeds

    def run_discovery(self) -> int:
        """运行所有启用的发现策略"""
        if not self.discovery_config.get("enabled", True):
            logger.info("[DiscoveryService] Discovery is disabled")
            return 0

        if self.is_paused:
            logger.info("[DiscoveryService] Pool full, waiting for processing")
            return 0

        all_discovered: List[dict] = []

        for strategy_name in self.strategies:
            strategy = self._get_strategy(strategy_name)
            if not strategy:
                logger.warning(f"[DiscoveryService] Unknown strategy: {strategy_name}")
                continue

            logger.info(f"[DiscoveryService] Running strategy: {strategy_name}")
            try:
                discovered = strategy.discover(
                    keywords=self.keywords,
                    existing_urls=self._get_existing_urls(),
                )
                logger.info(f"[DiscoveryService] {strategy_name}: found {len(discovered)} feeds")
                all_discovered.extend(discovered)
            except Exception as e:
                logger.error(f"[DiscoveryService] Strategy {strategy_name} failed: {e}")

        # 去重
        all_discovered = self._deduplicate_feeds(all_discovered)
        logger.info(f"[DiscoveryService] After dedup: {len(all_discovered)} feeds")

        # 质量评估
        all_discovered = self._assess_quality(all_discovered)

        # 添加到推荐池（pending 条目不超过 pool_max）
        added = 0
        for feed in all_discovered:
            if self.pending_count >= self.pool_max:
                break
            feed["discovered_at"] = datetime.now().isoformat()
            feed["status"] = "pending"
            self.recommended_feeds.append(feed)
            added += 1

        # 保存
        self.config["recommended_feeds"] = self.recommended_feeds
        self.config["discovery_config"] = self.discovery_config
        self._save_config()

        logger.info(f"[DiscoveryService] Added {added} feeds to recommended pool")
        return added

    def get_pending_feeds(self) -> List[dict]:
        """返回待处理推荐列表"""
        return [f for f in self.recommended_feeds if f.get("status") == "pending"]

    def get_all_recommended(self) -> List[dict]:
        """返回所有推荐（包括已处理的）"""
        return self.recommended_feeds

    def approve(self, url: str, category: str) -> bool:
        """批准推荐：移动到 feeds"""
        feed = None
        for f in self.recommended_feeds:
            if f.get("feed_url") == url:
                feed = f
                break

        if not feed:
            logger.warning(f"[DiscoveryService] Recommended feed not found: {url}")
            return False

        feed["status"] = "approved"
        feed["approved_category"] = category
        feed["approved_at"] = datetime.now().isoformat()

        if "feeds" not in self.config:
            self.config["feeds"] = {}
        if category not in self.config["feeds"]:
            self.config["feeds"][category] = []
        self.config["feeds"][category].append({
            "feed_url": feed["feed_url"],
            "name": feed.get("name", ""),
            "added_via": "discovery",
            "source_strategy": feed.get("source_strategy", ""),
            "discovery_query": feed.get("discovery_query", ""),
            "reason": feed.get("reason", ""),
            "estimated_quality": feed.get("estimated_quality", "medium"),
            "approved_at": feed["approved_at"],
        })

        self.config["discovery_config"] = self.discovery_config
        self._save_config()
        logger.info(f"[DiscoveryService] Approved {url} -> category '{category}'")
        return True

    def reject(self, url: str) -> bool:
        """拒绝推荐：从 recommended_feeds 删除"""
        for f in self.recommended_feeds:
            if f.get("feed_url") == url:
                f["status"] = "rejected"
                f["rejected_at"] = datetime.now().isoformat()
                logger.info(f"[DiscoveryService] Rejected {url}")
                self.config["discovery_config"] = self.discovery_config
                self._save_config()
                return True

        logger.warning(f"[DiscoveryService] Recommended feed not found for rejection: {url}")
        return False

    def refresh_pool(self, count: int = 5) -> List[dict]:
        """换一批：从 pending 里随机返回部分"""
        pending = self.get_pending_feeds()
        if not pending:
            return []
        return random.sample(pending, min(count, len(pending)))

    def get_pool_status(self) -> dict:
        """获取池状态摘要"""
        total = len(self.recommended_feeds)
        pending = sum(1 for f in self.recommended_feeds if f.get("status") == "pending")
        approved = sum(1 for f in self.recommended_feeds if f.get("status") == "approved")
        rejected = sum(1 for f in self.recommended_feeds if f.get("status") == "rejected")

        return {
            "enabled": self.discovery_config.get("enabled", True),
            "pool_max": self.pool_max,
            "pool_current": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "is_paused": self.is_paused,
        }

    def set_enabled(self, enabled: bool):
        """启用/禁用发现"""
        self.discovery_config["enabled"] = enabled
        self.config["discovery_config"] = self.discovery_config
        self._save_config()

    def cleanup_processed(self, keep_recent: int = 50):
        """清理已处理的推荐，保留最近 N 条"""
        processed = [f for f in self.recommended_feeds if f.get("status") != "pending"]
        pending = [f for f in self.recommended_feeds if f.get("status") == "pending"]
        processed.sort(
            key=lambda x: x.get("approved_at") or x.get("rejected_at") or "",
            reverse=True,
        )
        kept_processed = processed[:keep_recent]
        self.recommended_feeds = pending + kept_processed
        self.config["recommended_feeds"] = self.recommended_feeds
        self._save_config()
        logger.info(f"[DiscoveryService] Cleaned up, kept {len(kept_processed)} processed feeds")

    def close(self):
        """关闭所有组件"""
        for strategy in self._strategy_instances.values():
            if hasattr(strategy, "close"):
                strategy.close()
        if self._quality_scorer:
            self._quality_scorer.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
