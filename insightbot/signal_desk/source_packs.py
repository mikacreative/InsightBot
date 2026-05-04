from __future__ import annotations

from copy import deepcopy


SOURCE_PACKS = {
    "marketing_comms_cn": {
        "id": "marketing_comms_cn",
        "name": "China Marketing Communications",
        "description": "Chinese marketing, brand, communication, and campaign sources.",
        "coverage": "Campaign cases, agency news, marketing industry opinions, brand communication examples.",
        "limitations": "May miss closed social platform content and client-specific category news.",
        "bias": ["China-heavy", "marketing-media-heavy", "case-heavy"],
        "freshness": "daily",
        "feeds": {
            "Marketing Communications": {
                "rss": [
                    "https://www.digitaling.com/rss # 数英网",
                    "https://www.meihua.info/feed # 梅花网",
                ],
                "keywords": ["营销", "品牌", "案例"],
                "prompt": "Keep client-relevant marketing communications cases and trends.",
            }
        },
        "search": {
            "enabled": True,
            "queries": ["中国 营销 案例 趋势", "品牌 营销 传播 案例"],
        },
    },
    "brand_marketing_global": {
        "id": "brand_marketing_global",
        "name": "Global Brand Marketing",
        "description": "Global brand, campaign, and marketing industry sources.",
        "coverage": "Global brand campaigns, marketing platform movement, and industry commentary.",
        "limitations": "May overrepresent English-language and US/Europe market examples.",
        "bias": ["global-heavy", "English-heavy", "campaign-heavy"],
        "freshness": "daily",
        "feeds": {
            "Global Brand Marketing": {
                "rss": [
                    "https://www.marketingdive.com/feeds/news/ # Marketing Dive",
                    "https://www.adweek.com/feed/ # Adweek",
                ],
                "keywords": ["brand", "campaign", "marketing"],
                "prompt": "Keep examples with clear relevance to brand, communication, content, or campaign work.",
            }
        },
        "search": {
            "enabled": True,
            "queries": ["brand campaign marketing case", "creative campaign brand marketing"],
        },
    },
    "ai_martech": {
        "id": "ai_martech",
        "name": "AI and Martech",
        "description": "AI, marketing technology, platform, and consumer-facing tool signals.",
        "coverage": "AI marketing applications, platform changes, martech products, and consumer-facing AI use cases.",
        "limitations": "May include technical AI news that needs editorial filtering for marketing relevance.",
        "bias": ["tech-heavy", "AI-heavy", "tool-heavy"],
        "freshness": "daily",
        "feeds": {
            "AI and Martech": {
                "rss": [
                    "https://blog.hubspot.com/marketing/rss.xml # HubSpot Marketing",
                    "https://technode.com/feed/ # TechNode",
                ],
                "keywords": ["AI", "martech", "platform"],
                "prompt": "Keep AI and platform changes only when they affect marketing, content, media, or client work.",
            }
        },
        "search": {
            "enabled": True,
            "queries": ["AI marketing trend case", "martech platform marketing update"],
        },
    },
}


def get_source_pack(pack_id: str) -> dict:
    return deepcopy(SOURCE_PACKS[pack_id])


def list_source_packs() -> list[dict]:
    return [deepcopy(item) for item in SOURCE_PACKS.values()]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def merge_source_packs(packs: list[dict]) -> dict:
    merged = {"feeds": {}, "search": {"enabled": False, "queries": []}, "trust": []}
    for pack in packs:
        merged["trust"].append(
            {
                "id": pack["id"],
                "name": pack["name"],
                "coverage": pack.get("coverage", ""),
                "limitations": pack.get("limitations", ""),
                "bias": list(pack.get("bias", [])),
                "freshness": pack.get("freshness", ""),
            }
        )
        for section, section_data in pack.get("feeds", {}).items():
            target = merged["feeds"].setdefault(
                section, {"rss": [], "keywords": [], "prompt": ""}
            )
            target["rss"] = _dedupe(target["rss"] + list(section_data.get("rss", [])))
            target["keywords"] = _dedupe(
                target["keywords"] + list(section_data.get("keywords", []))
            )
            prompt = section_data.get("prompt", "")
            if prompt and prompt not in target["prompt"]:
                target["prompt"] = (target["prompt"] + "\n" + prompt).strip()
        search = pack.get("search", {})
        if search.get("enabled"):
            merged["search"]["enabled"] = True
        merged["search"]["queries"] = _dedupe(
            merged["search"]["queries"] + list(search.get("queries", []))
        )
    return merged
