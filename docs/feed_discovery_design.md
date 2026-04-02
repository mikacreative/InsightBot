# 订阅源发现模块 · 产品设计文档

> **模块代号：** FeedDiscovery  
> **版本：** v1.0  
> **状态：** 设计中  
> **作者：** 小管（产品设计）

---

## 1. 背景与目标

### 1.1 现状
- InsightBot 通过管理员手动填写 RSS URL 来扩展信源
- 扩展信源依赖人工搜索，成本高、效率低、容易遗漏长尾优质源
- 现有 `config.json` 的 `feeds` 结构已稳定，不应做大面积改动

### 1.2 目标
- **自动发现**：后台周期性发现与已有板块关键词、行业领域相关的新 RSS 源
- **推荐过滤**：避免推荐已有源、重复源、无内容源
- **人工把关**：所有推荐源必须经管理员确认后才进入正式信源池
- **体验闭环**：推荐 → 处理 → 继续发现的完整循环，不打扰管理员，不堆积

---

## 2. 核心设计原则

| 原则 | 说明 |
|------|------|
| **不改动现有 config 结构** | 新增 `discovery_config` 和 `recommended_feeds` 两个独立根级 key |
| **发现与执行分离** | 发现逻辑独立为 Service，可被定时任务调用，不耦合主推送流程 |
| **去重是工程核心** | 以 URL 精确去重 + 内容相似度兜底，避免推荐池膨胀 |
| **管理员始终有控制权** | 可随时暂停/启用、调整池阈值、手动清空池 |

---

## 3. 数据结构设计

### 3.1 config.json 扩展结构

```json
{
  "feeds": {
    "💡 营销行业": {
      "rss": ["https://..."],
      "keywords": ["广告公司", "营销案例"],
      "prompt": "..."
    }
  },

  "discovery_config": {
    "enabled": true,
    "interval_hours": 6,
    "pool_max": 20,
    "resume_after_processed": 5,
    "auto_resume": true,
    "discovery_strategies": ["search", "directory", "ai"]
  },

  "recommended_feeds": [
    {
      "feed_url": "https://example.com/rss",
      "source_strategy": "search",
      "discovery_query": "营销情报 AI",
      "matched_category": "💡 营销行业",
      "suggested_category": "💡 营销行业",
      "discovery_reason": "关键词「营销」命中现有板块 💡 营销行业",
      "discovered_at": "2026-04-02T10:00:00+08:00",
      "status": "pending",
      "title": "营销见闻",
      "description": "专注于营销行业的深度分析",
      "estimated_quality": "high",
      "tested_items_count": 5,
      "tested_recent_items": [
        {"title": "...", "link": "https://...", "published": "2026-04-01"}
      ]
    }
  ]
}
```

### 3.2 字段说明

#### `discovery_config`（发现配置）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `true` | 是否开启自动发现 |
| `interval_hours` | int | `6` | 两次发现之间的最小间隔（小时） |
| `pool_max` | int | `20` | 推荐池上限，达到后暂停发现 |
| `resume_after_processed` | int | `5` | 管理员处理多少条后恢复发现 |
| `auto_resume` | bool | `true` | 是否自动恢复；若为 false，需手动点"继续发现" |
| `discovery_strategies` | list[str] | `["search", "directory", "ai"]` | 启用的发现策略 |

#### `recommended_feeds`（推荐池）

| 字段 | 类型 | 说明 |
|------|------|------|
| `feed_url` | string | RSS 源 URL（精确去重key） |
| `source_strategy` | enum | 发现策略：`search` / `directory` / `ai` |
| `discovery_query` | string | 触发发现的搜索词/目录分类 |
| `matched_category` | string | 匹配到的已有板块名（用于推荐归属） |
| `suggested_category` | string | 系统建议归属的板块 |
| `discovery_reason` | string | 推荐理由（供管理员参考） |
| `discovered_at` | ISO8601 | 发现时间 |
| `status` | enum | `pending` / `added` / `ignored` / `expired` |
| `title` | string | RSS 源标题（从 feed 解析） |
| `description` | string | RSS 源描述 |
| `estimated_quality` | enum | `high` / `medium` / `low`（发现时估算） |
| `tested_items_count` | int | 测试抓取时获得的条目数 |
| `tested_recent_items` | list[dict] | 最近3条样本（标题+链接+时间，供管理员预览） |
| `processed_at` | ISO8601 | 处理时间 |
| `processed_by` | string | `admin` / `ai_batch`（批量操作来源） |

---

## 4. 发现策略设计

### 4.1 策略一：搜索引擎 RSS 搜索（`search`）

**原理：** 用已知板块的关键词，在搜索引擎中搜索 `site:xxx "RSS"` 或 `"feed URL"` 类型的页面。

**实现方式：**
1. 对每个板块，取其 `keywords` 列表 + 板块名作为搜索词
2. 构造搜索查询：`{keyword} RSS feed` 或 `{keyword} site:rsshub.app`
3. 调用搜索（`DuckDuckGo`），解析结果中包含 RSS 相关特征的 URL
4. 对候选 URL 进行去重过滤

**优势：** 覆盖面广，可发现任意网站的 RSS  
**成本：** 中等，每次发现约 10-20 次搜索请求

**示例搜索词：**
- `营销案例 RSS feed`
- `广告公关 最新资讯 feed`
- `AI 数字营销 RSS`

### 4.2 策略二：RSS 目录网站抓取（`directory`）

**原理：** 从已知的 RSS 目录/导航网站抓取，按分类索引发现新源。

**推荐目录源（维护列表）：**

| 目录名 | URL | 说明 |
|--------|-----|------|
| RSSHub | https://rsshub.app/routes | 收录大量中文站点的 RSS |
| Feed43 | https://feed43.com | 可将任意网页转为 RSS |
| 今日热榜 | https://tophub.today | 各平台热榜，部分有 RSS |
| RSS 搜索站 | https://www.rsssearch.net | 英文 RSS 搜索引擎 |

**实现方式：**
1. 维护一个固定的目录 URL 列表（不频繁变化）
2. 定期抓取，按分类页面遍历
3. 用板块关键词匹配分类，过滤候选

**优势：** 质量较高（目录已有筛选），实现成本低  
**成本：** 低，主要是对少数固定站点的抓取

### 4.3 策略三：AI 辅助发现（`ai`）

**原理：** 将已有板块的 `keywords` + `prompt` + 已有 RSS 源标题汇总发给 AI，让 AI 推荐相关网站/博客。

**Prompt 示例：**
```
已知板块「💡 营销行业」现有 RSS 源：
- 数英网 (digitaling.com)
- 梅花网 (meihua.info)
- AdWeek (adweek.com)

该板块关键词：广告公司, 公关公司, 营销案例
筛选标准：...

请推荐 5-10 个适合该板块的中国营销行业 RSS 订阅源（只需网站名和 URL），要求：
1. 与已有源不重复
2. 更新频率较高（至少周更）
3. 内容质量较高（行业媒体/专业博客，非自媒体）
只返回 JSON 数组：[["名称", "URL"], ...]
```

**优势：** 可发现目录未收录的垂直博客/小众媒体  
**成本：** 中等（每次调用 AI 一次），需注意频率控制

### 4.4 策略优先级与频率建议

| 策略 | 每次发现调用频率 | 优先级 |
|------|-----------------|--------|
| `directory` | 1次/天 | 高（质量稳定） |
| `search` | 1次/天 | 高（覆盖面广） |
| `ai` | 1次/周 | 中（补充长尾） |

---

## 5. 去重与质量过滤

### 5.1 去重层级

```
第1层：URL 精确去重
  └── 与 config.feeds[*].rss 中已有 URL 精确比对
  └── 与 recommended_feeds 中所有 URL 精确比对

第2层：域名去重（同域名只保留一个 RSS）
  └── 不同路径/子域名判断是否同源

第3层：内容相似度兜底（可选，AI 策略后执行）
  └── 对同类别下的候选，抽取最近3条标题，计算与已有源的语义相似度
  └── 相似度 > 0.85 的标记为重复，优先推荐质量更高的
```

### 5.2 质量过滤步骤

每个候选 RSS 源必须通过以下检查才进入推荐池：

| 步骤 | 检查项 | 通过标准 |
|------|--------|---------|
| 1 | HTTP 可达性 | 状态码 200/301/302，5秒内响应 |
| 2 | RSS 格式验证 | 能被 feedparser 解析，无致命错误 |
| 3 | 内容新鲜度 | 最近30天内至少有3条以上更新 |
| 4 | 域名非垃圾源 | 非已知广告联盟/内容农场域名黑名单 |
| 5 | 内容非空 | 测试抓取能获得至少3条有效条目 |

**Quality Score 估算（`estimated_quality`）：**
- `high`：通过全部检查，且测试条目 > 10 条，描述完整
- `medium`：通过全部检查，测试条目 3-10 条
- `low`：勉强通过（更新稀少/描述模糊）

---

## 6. 推荐池管理流程

### 6.1 发现 → 入池流程

```
[定时触发 发现任务]
       │
       ▼
[检查 discovery_config.enabled?]
       │ false → 跳过
       ▼
[检查 pool_size < pool_max?]
       │ false → 暂停，记录状态，等待处理
       ▼
[执行发现策略（directory → search → ai）]
       │
       ▼
[去重过滤（URL/域名/相似度）]
       │
       ▼
[质量过滤（5步检查）]
       │
       ▼
[分配 suggested_category（基于关键词匹配）]
       │
       ▼
[写入 recommended_feeds，status=pending]
       │
       ▼
[再次检查 pool_size >= pool_max?]
       │ true → 暂停发现，设置 paused_reason
       ▼
[完成]
```

### 6.2 管理员处理 → 恢复发现流程

```
[管理员在控制台处理推荐源]
       │
       ├── [添加到板块] → status=added，写入 config.feeds[category].rss
       ├── [忽略]       → status=ignored
       └── [批量处理]    → 批量标记 added/ignored
       
       │
       ▼
[更新 processed_at, processed_by]
       │
       ▼
[检查 auto_resume && 已处理数 >= resume_after_processed?]
       │ true → 重置发现状态，继续发现
       │ false → 等待手动触发（控制台按钮）
       ▼
[完成]
```

### 6.3 过期机制

- 推荐池中 `status=pending` 且 `discovered_at` 超过 **7 天** 的条目，自动标记为 `status=expired`
- 过期源不占用 pool_max 计数，但在池中保留记录（便于后续分析）
- 管理员可一键"清理过期"

---

## 7. 控制台交互设计

### 7.1 新增 Tab：🔍 信源发现

在现有 `scripts/app.py` 的 Tab 列表中新增一个 Tab，位于「板块与信源管理」右侧：

```
[📊 板块与信源管理] [🔍 信源发现] [⚙️ 推送版式定制] [🧠 AI 提示词调优] [📝 运行日志]
```

### 7.2 信源发现 Tab 布局

```
┌─────────────────────────────────────────────────────────┐
│ 🔍 订阅源发现                                            │
│                                                         │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│ │ 🟢 发现运行中  │ │ 📦 池中待处理 │ │ ⏸️  已暂停      │  │
│ │ 每6小时一次   │ │   12/20 条   │ │ 阈值:20,等处理5条│  │
│ └──────────────┘ └──────────────┘ └──────────────────┘  │
│                                                         │
│ [▶️ 继续发现] [⏸️ 暂停发现] [🗑️ 清空推荐池]              │
└─────────────────────────────────────────────────────────┘
```

### 7.3 推荐池列表（核心交互区）

**分页展示**，默认每页 10 条，支持按「状态/类别/质量」筛选：

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 推荐源列表                    [筛选: 全部▼] [排序: 发现时间▼]  [换一批🔄] │
├──────────────────────────────────────────────────────────────────────────┤
│ ○ 全选  ☑ 编号  来源策略  源标题        推荐理由          质量  操作    │
│ □     1 search  营销见闻    关键词「营销」命中...  🟢高   [添加▼][忽略]  │
│ □     2 directory 数字变量   来自RSSHub分类...    🟡中   [添加▼][忽略]  │
│ □     3 ai      AI前线周刊   AI推荐...           🟢高   [添加▼][忽略]  │
└──────────────────────────────────────────────────────────────────────────┘
│ 🟢 高质量  🟡 中等  🔴 低质量（建议忽略）                              │
```

**「添加」按钮下拉：** 列出所有现有板块，供选择添加到哪里

**「换一批」按钮：** 用随机/轮询方式展示池中未处理条目（避免管理员总看到同样顺序）

### 7.4 源详情展开

点击某条源可展开详情：

```
▼ 数字变量 (digitalvariables.com/rss)
   URL: https://digitalvariables.com/rss
   发现策略: search | 发现词: "数字营销"
   推荐理由: 关键词「数字营销」命中板块「🤖 数智前沿」
   发现时间: 2026-04-02 10:00
   
   📰 最近内容预览:
   · AI如何改变内容营销（2026-04-01）https://...
   · 2026年营销技术趋势（2026-03-30）https://...
   · 数据驱动的内容策略（2026-03-28）https://...
   
   [添加到 💡 营销行业 ▼] [添加到 🤖 数智前沿 ▼] [忽略] [关闭]
```

### 7.5 批量操作

在列表顶部选中多条后：

```
已选择 3 条  → [☑ 批量添加到板块 ▼] [☑ 批量忽略] [☐ 批量删除"]
```

### 7.6 发现配置面板（侧边或子区块）

```
⚙️ 发现配置
─────────────────────────────────
☑ 开启自动发现
  发现间隔： [6] 小时
  池上限：   [20] 条
  处理N条后恢复： [5] 条
☑ 自动恢复发现

发现策略：
☑ 搜索引擎 RSS 搜索
☑ RSS 目录网站抓取  
☐ AI 辅助发现（消耗 AI 调用额度）

[💾 保存配置]
```

---

## 8. API / 服务接口设计

### 8.1 模块结构

```
insightbot/
  feed_discovery/
    __init__.py
    discovery_service.py   # 主编排逻辑
    strategies/
      __init__.py
      search_strategy.py    # 策略一：搜索引擎
      directory_strategy.py # 策略二：目录抓取
      ai_strategy.py        # 策略三：AI推荐
    dedup.py                # 去重服务
    quality_filter.py       # 质量过滤
    models.py               # 数据模型（Pydantic 可选）
    scheduler.py            # 定时调度包装
```

### 8.2 核心接口

```python
# discovery_service.py

class FeedDiscoveryService:
    def __init__(self, config_path: str):
        """加载配置，建立与 config.json 的读写连接"""

    def run_discovery(self, force: bool = False) -> DiscoveryResult:
        """
        执行一轮发现。
        force=True 跳过间隔检查（管理员手动触发）。
        返回：成功发现数、跳过数、错误数、当前池状态
        """

    def add_to_pool(self, feed_url: str, ...) -> bool:
        """将候选源加入推荐池"""

    def approve_feed(self, feed_url: str, category: str) -> bool:
        """管理员操作：将源加入指定板块"""

    def reject_feed(self, feed_url: str) -> bool:
        """管理员操作：忽略源"""

    def batch_approve(self, feed_urls: list[str], category: str) -> BatchResult:
        """批量添加"""

    def batch_reject(self, feed_urls: list[str]) -> BatchResult:
        """批量忽略"""

    def refresh_pool_display(self) -> list[RecommendedFeed]:
        """换一批：返回池中随机排序的待处理源"""

    def get_pool_status(self) -> PoolStatus:
        """返回当前池状态摘要（数量/是否暂停/原因）"""

    def check_auto_resume(self) -> bool:
        """检查是否可以自动恢复发现"""

    def cleanup_expired(self) -> int:
        """清理过期条目，返回清理数量"""
```

### 8.3 定时调度

```python
# scheduler.py

def setup_discovery_cron(interval_hours: int = 6):
    """写入 crontab，与现有每日推送任务独立"""
    # 独立 cron job，comment="feed_discovery_task"
    # 不影响主推送任务的执行
```

---

## 9. 与现有系统的集成

### 9.1 配置读写

- `recommended_feeds` 和 `discovery_config` 写入 `config.json`（同文件读写，加锁）
- `feeds` 结构**完全不改动**，发现模块只读不写
- 推荐源被「添加」时，**追加写入**对应板块的 `rss` 列表

### 9.2 Streamlit 控制台集成

在 `scripts/app.py` 中新增 Tab，复用现有的 `load_config()` / `save_config()` 函数。

```python
with tab_discovery:
    discovery_tab(config, load_config, save_config)  # 新增函数
```

### 9.3 日志集成

- 发现任务的日志复用现有 `insightbot/logging_setup.py`
- 日志级别：`INFO`（发现进度）、`WARNING`（某策略失败）、`ERROR`（彻底失败）

---

## 10. 实现成本估算

### 10.1 模块拆分

| 模块 | 复杂度 | 预估行数 | 优先级 |
|------|--------|---------|--------|
| `directory_strategy` | 低 | ~100行 | P0 |
| `search_strategy` | 中 | ~200行 | P0 |
| `quality_filter` + `dedup` | 中 | ~200行 | P0 |
| `discovery_service` 编排层 | 中 | ~300行 | P0 |
| Streamlit 控制台 Tab | 中 | ~300行 | P0 |
| `ai_strategy` | 低 | ~100行 | P1（可后置） |
| `scheduler` | 低 | ~50行 | P0 |
| 过期清理 | 低 | ~30行 | P1 |

**P0 优先交付：** 基础发现 + 质量过滤 + 推荐池 + 控制台  
**P1 迭代：** AI 辅助发现 + 相似度去重 + 统计分析

### 10.2 第三方依赖

- 已有 `feedparser`：RSS 解析（已有）
- `requests`：HTTP 抓取（已有）
- `DuckDuckGo Search`（新）：`duckduckgo-search` pip 包，无 API key
- 无需新增重型依赖

---

## 11. 异常处理与边界情况

| 场景 | 处理方式 |
|------|---------|
| 搜索被反爬 | 降级到 directory 策略，记录 warning |
| RSS 测试超时 | 跳过该候选，记录 reason="timeout" |
| config.json 被手动编辑损坏 | 捕获 JSONDecodeError，用备份回滚 |
| 池已满但 auto_resume=false | 显式提示管理员，需手动点击恢复 |
| AI 策略返回格式错误 | 降级为静默忽略，不影响其他策略 |
| 发现任务执行中管理员同时操作 | 加文件锁，或用 session_state 临时标记 |

---

## 12. 未来扩展方向（不进入本期）

1. **RSS 源健康度监控**：定期检查已有源是否失效，提示管理员替换
2. **发现效果分析**：统计各发现策略的采纳率，优化策略权重
3. **语义去重升级**：用 embedding 向量做内容相似度匹配
4. **管理员可配置白名单域名**：屏蔽已知低质源（内容农场）
5. **发现任务 Webhook 通知**：推荐池达到阈值时，主动推企业微信提醒

---

*文档版本：v1.0 | 制定日期：2026-04-02 | 下一步：开发评审 + 任务拆分*
