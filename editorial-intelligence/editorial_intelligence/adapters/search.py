"""
Multi-provider search adapter.

Supports DuckDuckGo, Brave Search, 博查等，按配置权重分发请求。
每个 provider 可独立开关，切换时无需改代码。

使用方式：
    from editorial_intelligence.contracts import SearchProvider, DEFAULT_SOURCE_WEIGHT

    config = SourceWeightConfig(
        search_providers={
            "duckduckgo": SearchProvider(
                provider_id="duckduckgo",
                name="DuckDuckGo",
                weight=0.6,
                enabled=True,
            ),
            "brave": SearchProvider(
                provider_id="brave",
                name="Brave Search",
                base_url="https://api.search.brave.com/res/v1/web/search",
                api_key="YOUR_BRAVE_API_KEY",
                weight=0.4,
                enabled=True,
            ),
        }
    )

    adapter = SearchAdapter(providers_config=config)
    results = adapter.collect(queries=["AI 营销趋势 2026"])
"""

import logging
from typing import Any

from ..contracts.source_weight import SearchProvider, SourceWeightConfig

logger = logging.getLogger(__name__)


class SearchAdapter:
    """
    Multi-provider search adapter.

    Dispatches queries to one or more registered search providers,
    weighted by provider priority. Results are normalized to NormalizedSignal.
    """

    def __init__(
        self,
        providers_config: SourceWeightConfig | None = None,
        default_queries: list[str] | None = None,
    ):
        self.providers_config = providers_config or SourceWeightConfig()
        self.default_queries = default_queries or []

    def collect(
        self,
        queries: list[str] | None = None,
        provider_ids: list[str] | None = None,
        top_k: int = 5,
        **kwargs: Any,
    ) -> list:
        """
        Search across configured providers.

        Args:
            queries: List of search queries.
            provider_ids: Specific providers to use. If None, use all enabled.
            top_k: Max results per provider per query.
        """
        queries = queries or self.default_queries
        if not queries:
            return []

        # Determine which providers to use
        providers = self._resolve_providers(provider_ids)
        if not providers:
            logger.warning("No enabled search providers found")
            return []

        all_signals: list = []
        for query in queries:
            for provider in providers:
                try:
                    signals = self._search_provider(provider, query, top_k)
                    all_signals.extend(signals)
                except Exception as e:
                    logger.warning(f"Provider {provider.provider_id} failed for query '{query}': {e}")

        logger.info(f"Search collected {len(all_signals)} signals from {len(providers)} providers")
        return all_signals

    def _resolve_providers(
        self, provider_ids: list[str] | None
    ) -> list[SearchProvider]:
        """Return sorted list of providers to use, highest weight first."""
        all_providers = self.providers_config.search_providers

        if provider_ids:
            selected = [
                p for pid in provider_ids
                if (p := all_providers.get(pid)) and p.enabled
            ]
        else:
            selected = [p for p in all_providers.values() if p.enabled]

        selected.sort(key=lambda p: p.weight, reverse=True)
        return selected

    def _search_provider(
        self, provider: SearchProvider, query: str, top_k: int
    ) -> list:
        if provider.provider_id == "duckduckgo":
            return self._duckduckgo_search(query, top_k)
        elif provider.provider_id == "brave":
            return self._brave_search(provider, query, top_k)
        elif provider.provider_id == "bocha":
            return self._bocha_search(provider, query, top_k)
        else:
            logger.warning(f"Unknown provider: {provider.provider_id}")
            return []

    # -------------------------------------------------------------------------
    # Provider implementations
    # -------------------------------------------------------------------------

    def _duckduckgo_search(self, query: str, top_k: int) -> list:
        """DuckDuckGo via ddgs library (no API key required)."""
        try:
            from ddgs import DDGS
        except ImportError:
            logger.warning("ddgs not installed: pip install ddgs")
            return []

        signals: list = []
        try:
            with DDGS() as ddgs:
                for i, result in enumerate(ddgs.text(query, max_results=top_k)):
                    if i >= top_k:
                        break
                    from .base import NormalizedSignal

                    signals.append(
                        NormalizedSignal(
                            source_type="agent_search",
                            source_id="duckduckgo",
                            title=result.get("title", ""),
                            summary=result.get("desc", ""),
                            url=result.get("href", ""),
                            published_at="",
                            signals={"provider": "duckduckgo", "query": query},
                            raw=result,
                        )
                    )
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")

        return signals

    def _brave_search(
        self, provider: SearchProvider, query: str, top_k: int
    ) -> list:
        """Brave Search API."""
        import httpx

        from .base import NormalizedSignal

        signals: list = []
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": provider.api_key,
        }
        params = {"q": query, "count": top_k}

        try:
            resp = httpx.get(
                f"{provider.base_url}/search",
                headers=headers,
                params=params,
                timeout=provider.timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("web", {}).get("results", [])[:top_k]:
                signals.append(
                    NormalizedSignal(
                        source_type="agent_search",
                        source_id="brave",
                        title=item.get("title", ""),
                        summary=item.get("description", ""),
                        url=item.get("url", ""),
                        published_at="",
                        signals={"provider": "brave", "query": query},
                        raw=item,
                    )
                )
        except Exception as e:
            logger.warning(f"Brave Search failed: {e}")

        return signals

    def _bocha_search(
        self, provider: SearchProvider, query: str, top_k: int
    ) -> list:
        """博查 AI 搜索 API. https://api.bocha.cn/v1/ai-search"""
        import httpx

        from .base import NormalizedSignal

        signals: list = []
        base_url = provider.base_url or "https://api.bocha.cn"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "count": top_k}

        try:
            logger.info(f"Bocha request: base_url={base_url}, query={query}")
            resp = httpx.post(
                f"{base_url}/v1/ai-search",
                headers=headers,
                json=payload,
                timeout=provider.timeout_s,
                trust_env=False,
            )
            logger.info(f"Bocha response status: {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()

            # Bocha returns results in "messages" array
            # Each message has content="{\"webSearchUrl\":\"...\",\"value\":[...]}"
            messages = data.get("messages", [])
            items = []
            for msg in messages:
                if msg.get("type") == "source" and msg.get("content_type") == "webpage":
                    try:
                        import json as _json
                        content_str = msg.get("content", "{}")
                        content_obj = _json.loads(content_str)
                        web_results = content_obj.get("value", [])
                        for r in web_results:
                            item_url = r.get("url", "") or r.get("webSearchUrl", "")
                            if item_url and item_url.startswith("http"):
                                items.append({
                                    "title": r.get("name", ""),
                                    "snippet": r.get("snippet", ""),
                                    "url": item_url,
                                })
                    except Exception:
                        pass

            logger.info(f"Bocha returned {len(items)} items")
            for item in items[:top_k]:
                signals.append(
                    NormalizedSignal(
                        source_type="agent_search",
                        source_id="bocha",
                        title=item.get("title", ""),
                        summary=item.get("snippet", ""),
                        url=item.get("url", ""),
                        published_at="",
                        signals={"provider": "bocha", "query": query},
                        raw=item,
                    )
                )
        except Exception as e:
            logger.warning(f"博查 Search failed: {e}")

        return signals

        return signals
