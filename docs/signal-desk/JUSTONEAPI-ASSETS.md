# JustOneAPI 本机资产盘点与接线记录 v8

日期：2026-10-12｜状态：**C 方案已落地，OAuth 已授权，端到端实测跑通，适配器已切 v4，证据等级已收敛为单一真源，费控门禁已接线，研究配方已与执行层核对，评论通路已接**｜作用域：主力机
配套：`DATA-SOURCES-v0.1.md` §2（能力面）／`scripts/justone_mcp_probe.py`（只读体检）／`scripts/check_v4_parser.py`（解析离线校验）／`config/pricing/justoneapi-pricing-20261011.csv`（官方价目表快照）

> **v3**：v2 沿用的"搜索接口本身带正文、无需 N+1 详情调用"结论**被实测推翻**（§2.5），成本模型重写（§6）。
> **v4**：按 Mika 决策**把 `providers.py` 从 v2 切到 v4**，同时修掉一处会让方法论失效的证据等级缺陷（§2.7）。这是本项目**首次真实修改 JustOneAPI 适配器代码**。
> **v5**：三件事——① 拿到**官方全量价目表**（296 端点 × 35 平台），据此**纠正此前靠余额差分"推测"的单价**（§2.8 A）；② 实测确认**千瓜 detail 接口不返回任何正文**，`qiangua_body` 是幻影等级（§2.8 B）；③ 把 `METHODOLOGY.md` §5.2 的八等级词表与代码现用词表**合并为单一真源 `grades.py`**，未知等级改为 fail-closed（§2.8 C）。
> **v5 增补**：把计费相关的全部说法对**官方使用指南**逐条核对（§2.9）。三条旧推断全部被官方确证（只有 `code=0` 计费／令牌上限非账户级／异步结算），并**发现一条我们没建模的配额轴——"每日成功请求次数"**（§2.9 C）。计费码表已转录进 `costcontrol.BILLING_CODES`，`settle()` 可按 code 结算。
> **v6**：**把付费读取真正接到门禁上**（§2.8 E）。此前 `costcontrol.require()` 全项目零调用——**花钱的路开着、门禁不在路上**。接线后暴露并修掉三处只在真接线时才显形的问题：**结算不释放预留**（会自己关闭的门禁）、**业务码藏在错误文案里**、**参数名撞车**。信封改为**只从 `SIGNAL_DESK_SPEND_LIMIT_CNY` 来**，**未声明即不花钱**。
> **v7（本版）**：**三种研究模式从"报价表"变成"执行层的额度来源"**（§2.8 F）。`RECIPE_CALLS` 此前只能被 `quote_recipe()` 报价，不能约束任何一次运行（所有计划共用一套 `BUDGET_DEFAULTS`）。照配方核对时发现 **`scan` 少报两次调用**（§3 要求挑战查询、§2.2 禁止把截断摘要当语言复用），配方由 **¥0.20 改为 ¥0.55**；`probe`／`frame` 核对后不变。额度现由 `RECIPE_ALLOWANCES`（导入时解析一次）派生，**任何一笔花费都带 `mode` 标记**，`costcontrol.report()` 因此可按模式分账。
> **v8（本版）**：**评论通路接通**（§2.5 E）。`get-note-comment/v2` 形状实测确证（第三个形状：`data` 是 dict）；`providers.JustOneApiAdapter.comments()` 接入 `enrich`——评论**跟随终选正文目标**读取（终选后按需取的同一纪律），逐页过门禁（`comment_reads` 预算项，**默认 0**，面向 §3.3／§3.4 任务显式开启），独立预留与结算、独立缓存；评论线程作为 `note_comment` 级证据条目入册。**顺带**：MCP 通路首次走了账本（探针调用先预留后结算）。

---

## 0. 结论摘要

1. **本机不需要"再做一套"。** codex 侧远程 MCP、codex 侧 skill、项目内 Python 适配器三形态均已就位；**缺的从来不是工具**。
2. **已按 Mika 决策执行 C 方案并验证成功**：新建 `~/.workbuddy/mcp.json` 声明 JustOneAPI MCP（URL-only），WorkBuddy 端内置 MCP SDK 的 OAuth 客户端**已自动完成 DCR + PKCE 授权**；2026-10-11 15:12 起 6 个工具在会话内可直接调用。
3. **端到端已跑通（本次真实调用 5 次）**：`search_note_v2` / `search_note_v4` / `get_note_detail_v1` 三者均 `code=0`，返回真实笔记数据。
4. **⚠️ 核心修正：搜索接口的 `desc` 是截断摘要（≤60 字符），不是完整正文。** v2 与 v4 **两版都是**——v2 实测 20 条全部 ≤60；v4 实测 **57 条中 25 条正好卡在 60（占 44%）**，硬截断无疑。要完整正文**必须**走 `get_note_detail_v1/v6`，即 **N+1 调用**。
5. **`url` 字段在搜索返回中恒为空**（v2 实测 20/20 为空；v4 连 `xsec_token` 都不给）。但 `id` 可用，裸 URL `https://www.xiaohongshu.com/explore/<id>` **实测 HTTP 200 可访问**，无需 `xsec_token`。
6. **官方单价（已由价目表确证，非推测）**：`search-note/v2` **¥0.15**、`get-note-detail/v1` **¥0.15**、`get-note-detail/v6` **¥0.15**、`get-note-comment/v2` **¥0.15**、`search-note/v4` **¥0.20**。⚠️ **本版纠正**：detail 此前被记为"未观察到扣费／≤¥0.10"，实为与 v2 同价的 **¥0.15**——原因是计费**异步结算**（调用 2 结束余额未动、调用 3 才一并体现），单次差分反推会漏记（§2.8 A）。
7. **codex 的 OAuth access_token 无法直接复用**：实测寿命仅 **3599 秒（约 1 小时）**。长期有效的是 OAuth 刷新机制（现由 WorkBuddy 自行维护）或控制台静态 API Token。
8. **Cloudflare 坑**：MCP 域名对非浏览器指纹返回 `403 Error 1010`；REST 域名不受影响。已在 mcp.json 显式带浏览器 UA 规避。
9. **预算上限已设**（2026-10-11 晚）：令牌从 `Default` 换为 **`SignalDeskTest`**，`budgetAmount: 10.9`、`usedAmount: 0.9`、`remainingAmount: 10`。⚠️ **该上限是「令牌级」而非「账户级」**——它只约束绑定此令牌的通路；若 codex 侧仍用 `Default` 令牌，那条通路不受此上限保护，共享同一账户余额。
10. **适配器已切 v4 + 修复证据等级缺陷**（v4 内容，§2.7）：`search-note/v2` → **v4**（参数名同步改名）；`source_grade` 从 `'search excerpt'` 改为 **`'search_snippet'`**——前者不在下游低等级词表内，曾被误判为中等级、**静默绕过"仅有摘要不能支持完整判断"这条编辑守卫**。
11. **证据等级已收敛为单一真源**（本版新增，§2.8 C）：新建 `insightbot/signal_desk/grades.py` 承载八等级 + rank + `summary_only` + kind 谓词 + legacy alias 表；`search_snippet` 等 legacy token 归一为 `note_segment`。**未知等级一律 fail-closed 归为 `unverified`（rank 0）**——此类静默失效缺陷不会再有第二次。
12. **⚠️ 映射后的真实后果：千瓜内容被完全排除在可交付卡片之外**（本版新增，§2.8 C）。`qiangua_body` 归一为 `note_segment`（`summary_only=True`），而 `editorial_v2` 守卫现在对所有 `summary_only` 材料生效 → **千瓜单源证据无法再支撑任何完整判断**。这是"摘要 ≠ 正文"方法论的必然结果，但**显著改变产出面**，需 Mika 知晓。
13. **费控中台已落地**（§2.8 D 新增）：`pricing.py`（报价）+ `costcontrol.py`（门禁 + 账本）两层，把价目表变成**产品自身的额度治理能力**，而非仅一份参考文档。三条研究配方成本上限：`scan` **¥0.55** ／ `probe` ¥0.85 ／ `frame` ¥1.50；**v0.2.6 起配方同时是执行层的额度来源**（§2.8 F）。

---

## 1. 资产清单

| # | 资产 | 位置 | 形态 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | Codex MCP server | `~/.codex/config.toml` → `[mcp_servers.justoneapi]` | 远程 HTTP（OAuth） | 已注册、已真实调用成功 |
| 2 | Codex skill | `~/.codex/skills/justoneapi-social-listening/` | skill（3 文件 12K） | 已装，codex 侧可用 |
| 3 | 项目代码适配器 | `insightbot/signal_desk/providers.py` | Python 直连 REST | **已接进主流程**，只差 token |
| 4 | **WorkBuddy 自定义 MCP** | `~/.workbuddy/mcp.json` | 远程 HTTP（OAuth） | ✅ **已信任 + 已授权，本次实测可用** |
| 5 | 体检脚本 | `scripts/justone_mcp_probe.py` | Python CLI（只读） | ✅ 已实测通过 |
| 6 | 独立 CLI（官方） | — | — | **不存在**（官方仅 MCP + REST） |

### 1.1 Codex MCP server

```toml
[mcp_servers.justoneapi]
url = "https://mcp.justoneapi.com/mcp"
```

暴露 6 个工具（`refresh_catalog` 仅运营方，远程 OAuth 不开放）：

| 工具 | 作用 | 计费 |
| --- | --- | --- |
| `list_platforms` | 平台与端点数 | 否 |
| `search_endpoints` | 自然语言找端点（`limit` 默认 8／上限 20，可带 `platform` 过滤） | 否 |
| `get_endpoint_schema` | 端点完整参数契约与示例 | 否 |
| `call_endpoint` | `endpoint_id` + `params`，**一次上游派发** | **是** |
| `get_account_balance` | 余额与币种 | 否 |
| `get_usage_summary` | 用量与花费趋势 | 否 |

OAuth scope：`mcp:catalog:read`／`mcp:api:call`／`mcp:account:read`。
**无自动重试**——不确定的超时、网络错误、HTTP 502/503/504 一律不重试（官方设计，与 `providers.py` 的 no-retry 策略一致）。

### 1.2 Codex skill：`justoneapi-social-listening`

| 文件 | 内容 |
| --- | --- |
| `SKILL.md`（58 行） | 强制工具顺序（`search_endpoints` → `get_endpoint_schema` → `call_endpoint`，禁止猜 endpoint_id／参数名／游标格式）；声誉研究四类 query family（品牌／体验／责任方／业务广度）；证据记录 12 字段清单；综合口径（不得从样本推总体普及率） |
| `references/official-mcp-notes.md`（42 行） | 官方工具语义、scope、错误码映射 |
| `agents/openai.yaml` | 展示名与默认 prompt |

错误码：`100 INVALID_TOKEN`／`301 COLLECT_FAILED`／`302 RATE_LIMITED`／`303 DAILY_QUOTA_EXCEEDED`／`400 VALIDATION_ERROR`／`500 INTERNAL_ERROR`／`600 PERMISSION_DENIED`／`601 INSUFFICIENT_BALANCE`／`602 TOKEN_LIMIT_EXCEEDED`。

> skill 的 `description` 自带边界：**不用于私号数据、不做互动操纵、不发内容**——与本项目"公开信号"定位一致，可直接继承。

### 1.3 项目代码适配器（已在主流程里）

`insightbot/signal_desk/providers.py`（**已切 v4**，见 §2.7）：

| 函数 | 行为 |
| --- | --- |
| `justone_search(keyword, note_time)` | `GET /api/xiaohongshu/search-note/**v4**`，`note_time ∈ {None, ALL, ONE_DAY, ONE_WEEK, HALF_YEAR}`，超时 120s，`code != 0` 抛业务错，缺 `data.notes` 抛 schema 错（**刻意不把异常当零结果**） |
| `justone_note_detail(note_id)` | `GET /api/xiaohongshu/get-note-detail/v1`，超时 45s |
| `search_to_input(result, brand, question)` | 归一化为 evidence：`platform/source_id/provider/url/title/excerpt/desc_length/body_verified/published_at/retrieved_at/query/source_grade/limitation`；URL 由 `https://www.xiaohongshu.com/explore/<id>` 拼出 |

接线现状：`workspace.py:14` 导入；`:135` **live 模式把 `JUSTONEAPI_TOKEN` 列为四项必需凭证之一**；`:137-141` 采集→归一化→**20 条样本上限**；`web.py:96` 暴露 `justoneapi_configured` 布尔位；`ui.html` 有配置态显示。

**实测暴露的三个适配器问题及处置**：

| # | 问题 | 影响 | 状态 |
| --- | --- | --- | --- |
| A | 用 `search-note/**v2**`，而 v2 的 `noteTime` 筛选官方标注**不精确**，且响应体 563K（v4 仅 131K） | 时间窗研究不可靠 + 带宽浪费 | ✅ **已修**（切 v4，参数名同步改 `sortType`／`timeFilter`／`noteType: 'ALL'`） |
| B | `search_to_input` 把搜索结果的 `excerpt` 当作摘要用，但**上游是截断到 60 字符**；且 `source_grade` 用词不在下游词表内 | 证据等级被高估，编辑守卫失效 | ✅ **已修**（`source_grade='search_snippet'` + `desc_length` + `body_verified: False`） |
| C | `workspace.py:137` 只取 `plan['queries'][0]` | 单 query 采集，多 query family 尚未落地 | ⏳ 未动（不在本次范围） |

### 1.4 WorkBuddy 自定义 MCP（已启用 ✅）

`~/.workbuddy/mcp.json`（chmod 600）：

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "justoneapi": {
      "type": "streamable-http",
      "url": "https://mcp.justoneapi.com/mcp",
      "headers": {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
      }
    }
  }
}
```

**为什么 URL-only 就够**（已逐环验证 + 实际授权成功）：

1. `POST https://mcp.justoneapi.com/mcp`（无鉴权）→ `401` 且带标准挑战头：
   ```
   www-authenticate: Bearer error="invalid_token", error_description="...",
     resource_metadata="https://mcp.justoneapi.com/.well-known/oauth-protected-resource/mcp"
   ```
2. 该 URL 返回 `authorization_servers: ["https://auth.justoneapi.com"]`、`bearer_methods_supported: ["header"]`
3. `https://auth.justoneapi.com/.well-known/oauth-authorization-server` 返回
   `authorization_endpoint: /oauth2/authorize`、`token_endpoint: /oauth2/token`、
   `registration_endpoint: /oauth2/register`、`grant_types_supported` 含 `refresh_token`、
   `token_endpoint_auth_methods_supported: ["none", "private_jwt"]`（**公开客户端，无需 client_secret**）、
   `code_challenge_methods_supported: ["S256"]`
4. WorkBuddy 客户端内已打包 MCP SDK 的 OAuth 客户端（在 app 包中检索到
   `oauth-protected-resource`×19、`WWW-Authenticate`×57、`registration_endpoint`×33、
   `code_challenge`×63、`mcpAuth`×42、`Mcp-Session-Id`×37）→ 自动走 DCR + PKCE 并自动刷新

> **验证结果**：Mika 已完成客户端授权；`list_platforms` / `get_account_balance` / `search_endpoints` / `get_endpoint_schema` / `call_endpoint` 五个工具在 WorkBuddy 会话内**均调用成功**。

---

## 2. 一手实测证据

### 2.1 历史调用（2026-09-29，本机 codex）⚠️ 部分结论已推翻

来源：`~/.codex/archived_sessions/rollout-2026-09-29T14-30-15-….jsonl`。

| 调用 | 结果 |
| --- | --- |
| `xiaohongshu.search_note_v2` + `{keyword:"二代 接班 创业", page:1, sort:"general"}` | 12.2s，`code=0`，`data.items[].note.desc` 样例为"很多文章会讲'二代该如何突围'…" |
| `xiaohongshu.get_note_detail_v1` × 2 | 16.3s，`data[0].note_list[0].desc` 全文＋`hash_tag[]`＋`comments_count:2001`／`collected_count:3713`＋`images_list` |

> ❌ **v2 曾据此推断"搜索接口本身带正文 → 不需要 N+1 详情调用"。该推断于 2026-10-11 被推翻**：当时看到的样例恰是一条**短笔记**，其"正文"本身就只有几十字，无法据此判断字段是否被截断。本次用 20 条样本做长度分布检验，截断证据明确（§2.5）。

### 2.2 2026-10-11 直连 MCP 复测（免费工具）

用 codex 钥匙串中的 access_token 直连 streamable-http 端点（全程只调免费工具）：

| 探测 | 结果 |
| --- | --- |
| `initialize` | HTTP 200；`serverInfo = {name: "justoneapi-mcp", version: "2.0.0"}`；`protocolVersion 2025-06-18` |
| `list_platforms` | **307 个端点**，覆盖 1688／AliExpress／Amazon／B站／豆瓣／抖音系／Facebook／IMDb／Instagram／京东／快手／LinkedIn／Pixabay／腾讯互选／Reddit／Shopee／淘宝天猫／TikTok／今日头条／Twitter／VCG／微博／公众号／视频号／闲鱼／小红书／小红书电商／小红书蒲公英／优酷／YouTube／知乎等 **34 个平台** |
| `get_account_balance` | `availableBalance 56.35`，`currency CNY`，`reservedAmount 0` |
| `get_usage_summary` | 令牌 `Default`／`status VALID`／`defaultToken true`；**`budgetAmount null`**；`totalAmount "0.0000"`；近 30 天日消费与近 13 个月月消费**全为 0** |
| `search_endpoints`（"笔记搜索" + platform=xiaohongshu） | `confidence: high`，`ranking_version: v2`，首条即 `xiaohongshu.search_note_v2`（`score: 100`）；返回结构含 `score`／`required_params`／`relevant_limitations`／`alternatives`（带 `recommended`／`compatible`）／`matched_capabilities` |

**读法**：余额是可用真金（免费调用不计入 spending，故累计消费为 0）。**未设预算上限是个风险点**，建议在控制台设置。

> **平台宽度提示**：34 个平台意味着 Signal Desk 的"只做小红书"是个可选项而不是约束。抖音系（含巨量星图 33 端点）、微信公众号（22）、视频号（14）、知乎（14）、微博（11）都在同一账户同一余额下可用——**跨平台叙事能力已在采购面内**，无需追加供应商。

### 2.3 Cloudflare 拦截（重要坑）

| 请求 | 结果 |
| --- | --- |
| `mcp.justoneapi.com` + Python urllib 默认 UA | **`403 Error 1010: browser_signature_banned`**（`error_category: access_denied`） |
| `mcp.justoneapi.com` + 浏览器 UA | HTTP 200 ✅ |
| `api.justoneapi.com`（REST）+ urllib 默认 UA | 到达 API 层，返回正常 JSON（`{"code":100,"message":"TOKEN INVALID/UNACTIVATE"}`） |
| `api.justoneapi.com`（REST）+ `python-httpx/0.27.0` UA | 同上，正常 JSON ✅ |

**结论**：只有 MCP 域名启用了浏览器指纹校验。
- 对 `providers.py`（走 REST）**无影响** —— 已用三种 UA 验证均放行。
- 对 WorkBuddy（Electron／Node 指纹）**有风险** → 已在 mcp.json 显式指定浏览器 UA 规避。

### 2.4 端点契约（MCP 目录实测，均非 deprecated）

| `endpoint_id` | 标题 | 必填参数 | 备注 |
| --- | --- | --- | --- |
| `xiaohongshu.search_note_v2` | 关键词笔记搜索 | `keyword` | 可选 `page`／`sort`(general／popularity_descending／time_descending／comment_descending／collect_descending)／`noteType`(_0／_1／_2)／`noteTime`(ONE_DAY／ONE_WEEK／HALF_YEAR)。**官方 WARNING：`noteTime` 筛选不精确** |
| `xiaohongshu.search_note_v4` | 关键词笔记搜索 | `keyword` | 官方推荐用于**准确发布时间筛选**；字段更精简（18 vs 32），响应体小 4 倍 |
| `xiaohongshu.get_note_detail_v1` | 笔记详情 | `note_id`（支持 explore URL） | **不支持视频下载** |
| `xiaohongshu.get_note_detail_v6` | 笔记详情 | `note_id` | v1 的 `alternatives`（`compatible`，非 recommended） |
| `xiaohongshu.get_note_comment_v2` | 笔记评论 | `note_id` | 游标分页 `lastCursor`；`sort ∈ {normal, latest, like_count}`，官方建议**默认 `latest`**，取不到时改 `normal` 重试 |
| `xiaohongshu.get_note_sub_comment_v2` | 评论回复 | `note_id` + `comment_id` | 游标分页 |
| `xiaohongshu.get_topic_note_list_v1` | 话题笔记列表 | `topic_id` | 热门／最新排序 |
| `xiaohongshu.get_user_note_list_v4` | 用户笔记 | `user_id` | `lastCursor` 分页 |
| `xiaohongshu.search_recommend_v1` | 关键词联想 | — | 词库扩展 |
| `xiaohongshu.ask_dots_v1` | 平台 AI 问答 | `keyword` | 平台二次加工，引用需谨慎 |
| `creator.get_profile_v2` | 蒲公英创作者资料 | — | 达人方向 |

**命名空间差异（接线陷阱）**：MCP 用点号（`xiaohongshu.search_note_v2`），REST 用斜杠（`/api/xiaohongshu/search-note/v2`）。且**版本号不同步**——本机实调为 v2/v1，官网文档写 v4/v6。
→ **必须用 `search_endpoints` + `get_endpoint_schema` 实时探测，禁止写死版本号**；`providers.py` 目前硬编码 `/v2`、`/v1`，端点升版会静默失效。

### 2.5 ★ WorkBuddy MCP 端到端实测（2026-10-11 15:12，已授权）

关键词统一为 `泡泡玛特 新品`。**全部为真实计费调用。**

| # | 端点 | 条数 | 关键观察 |
| --- | --- | --- | --- |
| 1 | `search_note_v2` p1 | **20** | 响应体 563K；`data.items[].note` 32 字段 |
| 2 | `get_note_detail_v1` | 1 | 响应体 80K；`data[0].note_list[0]` **62 字段** |
| 3—5 | `search_note_v4` p1／p2／p3 | 17 × 3 = **57** | 响应体 131—184K；`data.notes[]` **18 字段**；p1 含 `total:17`、`has_more:true`、`statistics` |

#### A. `desc` 截断——推翻旧结论的决定性证据

| 端点 | desc 长度分布 | 判读 |
| --- | --- | --- |
| `search_note_v2`（20 条） | 最小 46／最大 **60**／均值 56.0；6 条 = 60 | 多条在句中被硬切：`"…还有哭娃的🍅，感"`、`"…左右摇轻微打"`、`"#跟拉布布一"` |
| `search_note_v4`（**57 条**，3 页） | 最小 25／最大 **60**／均值 57.2；**25 条正好 = 60（44%）** | 右端在 60 处堆积成尖峰——典型的硬截断分布，非自然长度分布 |
| `get_note_detail_v1`（同一条笔记） | **108** | 与 v2 该条的 59 形成对照：`"…[话题]# #潮玩[话题]# #潮玩新品[话题]# #礼物[话题]#"` 被搜索接口砍掉了后半段 |

> **结论**：`desc` 在**搜索结果中一律是 ≤60 字符的截断摘要**，v2/v4 两版皆然。**官网文档称"完整 desc"不成立**（或仅对特定响应示例成立）。
> **要完整正文 → 必须 `get_note_detail_v1/v6`，成本为 N+1 次调用。**
> 📁 **可复核样本**：`docs/signal-desk/evidence/justone-search-samples-20261011.jsonl`（**77 条**：v2 20 + v4 57，逐条含 `desc`／`desc_len`／四类互动／`timestamp`／`has_url`）。本表所有统计均由该文件直接算出，可独立复算。

同时也说明：本样本中该条笔记**正文本身极短**（108 字符全是话题标签），因此"截断"在不同笔记上的实际损失差异很大——**话题标签型笔记几乎无损，长文笔记损失巨大**。这对证据等级判定有直接影响：搜索结果只够支撑"提及与话题"层，不够支撑"论述与观点"层。

#### B. `url` 恒空，但可构造

| 端点 | `url` 字段 | 构造依据 | 实测 |
| --- | --- | --- | --- |
| `search_note_v2` | **20/20 为空** | 有 `id` + `xsec_token` | `https://www.xiaohongshu.com/explore/<id>?xsec_token=…&xsec_source=pc_search` → **HTTP 200** |
| `search_note_v4` | 无此字段 | 只有 `id`（**无 `xsec_token`**） | `https://www.xiaohongshu.com/explore/<id>`（**裸 URL**） → **HTTP 200** |

> **结论**：**裸 URL 即可访问**（实测 200），不需要 `xsec_token`。这简化了归一化逻辑——`search_to_input` 现有的拼 URL 方式正确。
> 注：HTTP 200 只证明页面可达；小红书为客户端渲染，页面是否呈现完整内容未在无头环境下进一步验证。

#### C. `get_note_detail_v1` 实际字段（62 个，摘录高价值项）

| 字段 | 本次取值 | 用途 |
| --- | --- | --- |
| `desc` | **完整正文**（108 字符，含 `[话题]#` 标记） | L1 证据正文 |
| `hash_tag[]` | 完整数组：`{id, name, link, record_count, record_emoji}` | 话题归因 |
| `topics[]` | 完整数组：`{id, image, link, discuss_num, activity_online}` | 活动／话题追踪 |
| `ip_location` | `湖南` | 地域分布（千瓜需另调接口） |
| `liked_count` / `comments_count` / `collected_count` / `shared_count` | `2260` / `466` / `357` / `4733` | 互动强度 |
| `user` | `{nickname, red_id, userid}` | 作者归因 |
| `time` | 秒级时间戳 `1791540718` | 时间窗 |
| `view_count` | **`0`** | ⚠️ 未回填，不可用 |
| `comment_list`（顶层） | **`[]` 空** | ⚠️ 详情**不**顺带返回评论，评论须另调 `get_note_comment_v2` |
| `images_list` / `foot_tags` / `head_tags` / `ats` / `note_statement` / `cooperate_binds` / `goods_info` | 存在 | 图文、@关系、商单标识、带货 |

#### D. `search_note_v4` 优于 v2 的三点

| 维度 | v2 | v4 |
| --- | --- | --- |
| 时间窗精度 | ⚠️ 官方标注 `noteTime` **不精确** | ✅ 推荐用于准确时间筛选 |
| 响应体 | 563K | **131K**（约 1/4） |
| 分页元数据 | 无 `total`／`has_more` 于顶层 | ✅ `total`、`has_more`、`statistics{total_items, note_count, video_count, ads_count}`、`recommend_queries`、`search_meta` |
| 互动字段 | 有 | 有（+`tags[]`、`geo_info`） |
| 单价 | ¥0.15／次 | ¥0.20／次 |

> **建议**：`providers.py` 应从 v2 切到 **v4**（时间窗可靠 + 体积小 → 对长时段趋势研究是硬需求），代价是单价高 0.05。

#### E. `get_note_comment_v2` 实测形状（2026-10-12，v8 增补）

**评论层（L1 评论子层）的通路实测**：1 次真实调用（¥0.15，`code=0`），note `6ac8bdee00000000140016dc`。**这次探针与以往不同：先经 `costcontrol.authorize(channel='mcp')` 预留、调用后 `settle(code=0)`——MCP 直调通路第一次走了账本**（"同一个信封的人工约定"落成了动作）。

**响应形状（第三个形状，与前两者都不同）**：

| 层 | 形状 |
| --- | --- |
| `search-note/v4` | `data.notes[]` |
| `get-note-detail/v1` | `data` 是 **list**，正文在 `data[0].note_list[0]` |
| **`get-note-comment/v2`** | `data` 是 **dict**：`comments[]`（10 条/页）＋ `comment_count` / `comment_count_l1` ＋ `has_more` ＋ **JSON 字符串游标** `cursor` |

**评论对象高价值字段**：`id` / `content` / `ip_location` / `like_count` / `time` / `note_id`（回读校验用）/ `sub_comment_count` ＋ `sub_comments[]`（**楼中楼内嵌在父评论里**，每条带 `target_comment.user`）/ `user{nickname, red_id, userid}`。

**接线要点**：参数名 `noteId`（接受 explore URL）；`sort` 默认 `latest`，官方建议取不到时改 `normal` 重试；`lastCursor` 游标分页。样本：`docs/signal-desk/evidence/justone-comment-sample-20261012.json`（截取 2 条＋1 楼中楼，字段结构保真）。

> **口径提醒**：一页评论是"该笔记最新 10 条"，是个体评论者的声音样本——**不构成代表性人群证据**（§2.2 评论层用途是异议、复购线索、未被回答的问题，不是人群占比）。另外本条笔记 detail 里 `comments_count: 466` 与评论端点 `comment_count: 473` **不一致**（口径差异未查证），引用评论数时以评论端点为准并标注时点。

### 2.6 单价：从"推测"到"确证"（2026-10-11）

**第一轮：余额差分（推测）**。余额轨迹（`get_account_balance`，免费）：

| 时点 | 余额 | 本步调用 | 表面扣费 |
| --- | --- | --- | --- |
| 起点 | 56.35 | — | — |
| 调用 1 后 | 56.20 | `search_note_v2` ×1 | 0.15 |
| 调用 2 后 | 56.20 | `get_note_detail_v1` ×1 | **0.00**（未即时结算） |
| 调用 3 后 | 56.00 | `search_note_v4` ×1 | 0.20 |
| 调用 5 后 | 55.60 | `search_note_v4` ×2 | 0.40 |
| **合计** | **−0.75** | **5 次** | — |

当时据此推断 `get_note_detail_v1` 为 ¥0.00～0.10。**⚠️ 这个推断是错的。**

**第二轮：官方价目表确证（本版）**。Mika 导出控制台全量价目表（296 端点 × 35 平台），据此交叉验证：

| 端点 | 官方单价 | 与差分是否自洽 |
| --- | --- | --- |
| `search-note/v2` | **¥0.15** | ✅ 一致 |
| `search-note/v4` | **¥0.20** | ✅ 一致（2 次观测，差分一致） |
| `get-note-detail/v1` | **¥0.15** | ⚠️ **修正**：5×理论值 0.90 − 实测 0.75 = **0.15**，恰好等于**一笔 detail 尚未入账** |
| `get-note-detail/v6` | ¥0.15 | — |
| `get-note-comment/v2` | ¥0.15 | 此前标"未测"，现已确证 |
| `ask-dots` | ¥0.50 | 小红书侧唯一高价端点 |

**结论**：**账户余额差分不足以推断单价**——异步结算会让单笔延迟入账，差值恰好伪装成"这个端点免费"。**单价必须以官方价目表为准，余额只用于对账（`reconcile()`）。**

> **方法论警告（保留）**：MCP 层没有 per-call 明细，`get_usage_summary` 只给金额趋势。**最终以 `dashboard.justoneapi.com` 账单为准。**

---

### 2.7 ★ 适配器切 v4 + 证据等级对齐（2026-10-11 15:28，v4 内容）

Mika 决策："设了上限。可以切 v4。"

#### A. v2 → v4 不是换 URL 那么简单：**参数名全改了**

若只把路径 `/v2` 改成 `/v4` 而不改参数名，**时间筛选会被静默忽略**、返回全量结果而让人以为筛过——这正是本文件反复警告的"版本不同步陷阱"的真实形态。实测 `get_endpoint_schema(xiaohongshu.search_note_v4)` 确认：

| v2 参数 | v4 参数 | 说明 |
| --- | --- | --- |
| `sort` | **`sortType`** | 枚举扩展为 `general` / `popularity_descending` / `time_descending` / `comment_descending` / `collect_descending` |
| `noteTime` | **`timeFilter`** | 枚举 `ALL` / `ONE_DAY` / `ONE_WEEK` / `HALF_YEAR` |
| `noteType: '_0'` | **`noteType: 'ALL'`** | 枚举 `ALL` / `VIDEO_NOTE` / `NORMAL_NOTE` |
| 返回 `data.items[].note` | **返回 `data.notes[]`** | v4 的数组元素**直接是 note 对象**，无 `model_type` 外层包裹 |

> v4 官方标注："这是移动应用版本接口。搜索结果更准确。"——与"v2 时间窗不精确"互相印证。

#### B. 顺带修掉一个会让方法论失效的缺陷：`source_grade` 用了词表外的值

`providers.py` 原先产出 `source_grade: **'search excerpt'**`，但下游的两处守卫只认另一套词：

- `core.py` `_excerpt_rank()`：低等级集合 = `('title_only', 'search_snippet', 'rss_snippet')`
- `editorial_v2.py:277`：`all(grade in ('title_only','search_snippet','rss_snippet'))` → 则报"仅有标题或摘要，不能支持完整判断"

**由于 `'search excerpt'` 不在集合里，它落到 `_excerpt_rank` 的兜底分支返回 1（中等级），且编辑守卫完全不触发** → 用 ≤60 字符截断摘要支撑的卡片会被放行。这与方法论 v0.2.1 §2.2 刚刚写下的"把截断摘要当正文引用，是这一版最容易犯的方法论错误"**恰好是同一个错误，只是发生在代码里**。

**当时修法（最小改动）**：把 `source_grade` 改为词表内的 **`'search_snippet'`**，并补 `desc_length` 与 `body_verified: False` 两个可程序化检查的字段。

> ⚠️ **这条"最小改动"已被 v5 的单一真源方案取代**：`'search_snippet'` 现为 legacy token，由 `grades.py` 归一为 `note_segment`。**根因不是"用错了词"，而是"存在两套词表"**——只要词表可以分叉，第三个 `'search excerpt'` 迟早会出现。见 §2.8 C。

#### C. 离线校验（零成本，不消耗余额）

`scripts/check_v4_parser.py` 用 2026-10-11 保存的**真实 v4 响应**（03 页共 57 条）喂给新解析逻辑，不联网、不耗额度：

```
parsed 57 notes across 3 pages; longest desc = 60 chars
grades produced: {'note_segment'}

--- evidence-grade guard ---
  grades.level("search_snippet")            = note_segment  (rank 1, summary_only=True)
  grades.level("search excerpt")            = note_segment  <- legacy token 归一
  grades.level("qiangua_body")              = note_segment  <- 幻影等级已降级
  grades.level("note_body")                 = note_body     (rank 3, summary_only=False)
  grades.level("something_unknown")         = unverified    <- fail-closed, rank 0
  editorial_v2 summary-only guard matches   = True
```

同批样本再一次印证截断：**57 条最长 60 字符**。

#### D. 本次改动的文件

| 文件 | 改动 |
| --- | --- |
| `insightbot/signal_desk/providers.py` | 切 v4；参数名改 `sortType`／`timeFilter`／`noteType`；解析改 `data.notes[]`；`source_grade` 修正；新增 `desc_length`／`body_verified`；`limitations` 重写；`collection` 补 `has_more`／`total` |
| `tests/signal_desk/test_workflow.py` | `test_verified_search_normalization` fixture 从 v2 结构改 v4 结构；新增测试把等级修复锁进测试 |
| `scripts/check_v4_parser.py` | 新建，真实响应离线校验 |

> ⚠️ **`total` 语义存疑（Mika 已裁定：保留，下次再验证）**：v4 实测 `total: 17` 而 `has_more: true`（第 2、3 页也各返回 17 条）。`total` 不像是结果总数，使用前需再验证。**本轮不动。**

---

### 2.8 ★ v5 三件事：价目表确证 / 千瓜幻影等级 / 证据等级单一真源

#### A. 官方全量价目表（`config/pricing/justoneapi-pricing-20261011.csv`）

**价目来源**：`https://dashboard.justoneapi.com/zh/dashboard/pricing`

> ⚠️ **该 URL 无公开页面**。2026-10-11 实测：匿名访问该路由会被重定向到登录页。官方文档也明确写"**您可以登录系统查看各个接口的具体价格**"（`https://docs.justoneapi.com/zh/usage`）。也就是说**控制台导出是唯一的官方价目来源**——这正是必须把它落盘为带日期的快照、而不是每次现查的原因。快照元数据已写入 `pricing.py` 的 `PRICE_SOURCE_URL`／`DOCS_USAGE_URL`／`EXPORTED_AT`。

Mika 导出控制台价目表，落盘为 296 行快照（列：`platform,endpoint_path,price_cny,permission`），并建 `insightbot/signal_desk/pricing.py` 作为报价层。

| 指标 | 值 |
| --- | --- |
| 端点数 | **296** |
| 平台数 | **35** |
| 不可定价 | **2**（`京东 /api/jd/get-item-detail/v2`、`pixabay /api/pixabay/search-image/v1`，均为 `未开通`） |
| 价格区间 | ¥0.05 — ¥1.50 |

价格档位分布（端点数）：

| 单价 | 端点数 | | 单价 | 端点数 |
| --- | --- | --- | --- | --- |
| ¥0.05 | 18 | | ¥0.40 | 2 |
| ¥0.10 | 108 | | ¥0.50 | 14 |
| ¥0.15 | 76 | | ¥0.55 | 1 |
| ¥0.20 | 45 | | ¥0.60 | 1 |
| ¥0.25 | 7 | | ¥0.80 | 6 |
| ¥0.30 | 8 | | ¥1.00 | 4 |
| | | | ¥1.50 | 4 |

**小红书侧**（16 端点）：15 个 ¥0.15、1 个 ¥0.20（`search-note/v4`）、1 个 ¥0.50（`ask-dots`）。**本项目的主链路恰好全部落在最便宜的 ¥0.15 档。**

`permission` 为 `unavailable` 的端点**一律不可计费**——`pricing.Quote.chargeable` 要求 `unit_price is not None and permission == 'allowed'`，因此未开通端点即使有标价也不会被误算进预算。

#### B. ⚠️ 千瓜 `note.search_by_url` 实测：不返回任何正文（决定性证据）

方法：用千瓜 CLI 真实拉取 `note.search_by_url`，逐字段检查。

**结果：返回 40 个字段，无任何内容字段。**

| 字段 | 实测 | 说明 |
| --- | --- | --- |
| `Title` | 17 字符 | 标题，非正文 |
| `Tag` | 空 | — |
| `VerifyContent` | **不存在** | 此前假设的正文载体 |

**推论**：`qiangua_body` 是一个**幻影等级**——代码里存在这个值，但它对应的能力**在任何接口上都不存在**。千瓜在本项目里**最高只能到 `note_segment`（摘要级）**。

**这直接影响 `note_body` 的唯一来源**：只有 JustOneAPI 的 `get-note-detail/v1|v6`。实测同一笔记：搜索接口 59 字符 vs 详情接口 **108 字符完整正文**。

> 这与 §2.5 的结论互为印证：**两个供应商的搜索接口都是截断摘要，正文只能从详情接口取。**

#### C. 证据等级单一真源（`insightbot/signal_desk/grades.py`）

**问题**：`METHODOLOGY.md` §5.2 定义了八等级词表，代码里却在用另一套零散词（`title_only`／`search_snippet`／`rss_snippet`／`qiangua_body`／`comment thread`…）。§2.7 B 那个静默失效缺陷，**根因就是词表可以分叉**。

**做法**：新建 `grades.py` 承载全部语义，四个调用点全部接入。

| 项 | 内容 |
| --- | --- |
| 八等级 | `note_meta`(0) ／ `note_segment`(1) ／ `note_comment`(2) ／ `note_body`(3) ／ `note_structure` ／ `note_linked` ／ `brand_structure` ／ `trend_series` |
| 标记值 | `unverified`（未知）、`external_context`（RSS 等站外上下文） |
| 公开 API | `split()` / `level()` / `kind()` / `rank()` / `summary_only()` / `is_note_text()` / `is_evidence()` / `is_comment()` / `is_body()` / `is_meta()` / `canonical()` / `describe()` |
| 版本号 | `GRADE_VOCABULARY_VERSION = '2026-10-11.1'` |

**Legacy alias 归一表**（历史 token 全部有归属，不靠兜底）：

| Legacy token | 归一为 |
| --- | --- |
| `title_only` | `note_meta` |
| `search_snippet` ／ `search excerpt` | `note_segment` |
| `qiangua_body` | `note_segment` ← **幻影等级降级** |
| `full_text` ／ `note body` ／ `note text` | `note_body` |
| `comment thread` ／ `qiangua comment thread` | `note_comment` |
| `rss_snippet` ／ `external context` | `external_context` |
| `unverified sample` | `unverified` |

**核心改动**：未知等级 **fail-closed**。

```python
def level(grade):
    token = split(grade)[0].strip().lower()
    token = _ALIASES.get(token, token)
    if token in _LEVELS or token in _MARKERS:
        return token
    return UNVERIFIED          # ← 不再"兜底成中等级"
```

> **rank 与 summary_only 是两个正交轴**：`note_segment` 的 rank=1（低），同时 `summary_only=True`。`rank` 回答"这条证据在阶梯上多高"，`summary_only` 回答"它是不是只有摘要、需要额外取证"。**不要把两者混为一个维度**——`grades.py` 内已显式注释。

**四例校验（离线，`scripts/check_v4_parser.py`）**：

```
note_segment        rank=1  summary_only=True
note_body           rank=3  summary_only=False
search_snippet   -> note_segment      (legacy)
something_unknown-> unverified        (fail-closed, rank=0)
```

**接入点**：

| 文件 | 改动 |
| --- | --- |
| `core.py` | `_excerpt_rank()` → `grades.rank()`；`_sample_kind()` → `grades.kind()`；默认值 → `grades.UNVERIFIED` |
| `editorial_v2.py` | 守卫由硬编码词表改为 `all(grades.summary_only(e['source_grade']) ...)` |
| `providers.py` | `'search excerpt'` → `'note_segment'` |
| `research_v2.py` | `_note()` 改 `'note_segment' if body else 'note_meta'`；补证判定改用 `grades.is_meta()`；字段更名 `title_only`→`summary_only`、`usable_bodies`→`bodies` |

> ⚠️ **重要后果（需 Mika 知晓）**：守卫改用 `grades.summary_only` 后，**千瓜的单源证据被完全排除在客户可交付卡片之外**——因为它最高只能是 `note_segment`。这是方法论的**正确**结果（摘要 ≠ 正文），但确实**改变了产出面**。若确需千瓜单源出卡，得走"补证"路径（用 JustOneAPI detail 补正文），而不是放宽守卫。

#### D. 费控 / 额度中台（`pricing.py` + `costcontrol.py`）

Mika 提问："也许可以让我们的产品本身能够有个费控、额度中台？" —— 已落地为三层结构，**让价目表从"参考文档"变成"产品能力"**。

| 层 | 文件 | 职责 |
| --- | --- | --- |
| ① 报价 | `pricing.py` | 版本化价目表；`normalize_id()` 归一端点命名；`quote()` / `price_of()` / `cheapest()` / `table_summary()` |
| ② 门禁 | `costcontrol.py` | 品牌 × 期信封（`Envelope`）；`authorize()` 预授权；未知单价 / 未开通端点**一律拒付**（`BudgetDenied`） |
| ③ 账本 | `costcontrol.py` | 追加式 JSONL（`data/signal-desk-spend.jsonl`，`0o600`）；`reserve` → `settle` 两阶段 |

**端点命名空间归一化**（同一端点走 REST 还是 MCP，必须是同一个 join key）：

```
REST  /api/xiaohongshu/search-note/v4  ─┐
                                        ├─→ xiaohongshu_search_note_v4
MCP   xiaohongshu.search_note_v4       ─┘
```

**pre-call reserve 语义**：授权时先写 `reserve` 行，调用完成后再写 `settle` 行。**目的是防止重试／并行／双通路对同一余额重复授权（双花）**——§7 那条"MCP 与 REST 共用余额"的风险，由此在账本层堵住。

**异步结算的处置**：由于 §2.6 已证计费延迟入账，**本地账本只是估算**；`reconcile()` 用账户余额差分对账，差额写回账本而非静默吞掉。

**研究配方成本上限**（对应方法论 §4 三模式）：

| 配方 | 调用构成 | 成本上限 |
| --- | --- | --- |
| `scan` | `search-note/v4` ×2 ＋ `get-note-detail/v1` ×1 | **¥0.55** |
| `probe` | `search-note/v4` ×2 ＋ `get-note-detail/v1` ×3 | **¥0.85** |
| `frame` | `search-note/v4` ×3 ＋ `get-note-detail/v1` ×6 | **¥1.50** |

**测试**：`tests/signal_desk/test_costcontrol.py` 26 项、`tests/signal_desk/test_spend_gate.py` 10 项、`tests/signal_desk/test_modes.py` 11 项、**`test_comment_reader.py` 10 项（v8）**全通过。总览 **413 passed, 0 failed**（标准命令 `env -u PYTHONPATH … pytest`；此前的"402 + kestra 既有失败"经查为 WorkBuddy shim 环境噪声，见 `LOCAL-V02.md` 2026-10-12）。

> **测试环境更正**：此前判断 `tests/signal_desk/` 被 module 级 `importorskip` 跳过（"缺隔离运行时"）——**实测发现 `.venv-signal-desk/bin/python` 依赖齐全（含 `langgraph`／`httpx`／`requests`）**，本轮起改为**真实 pytest 全量运行**，不再用离线回放替代。§2.7 C 的离线校验保留为**零成本前置门禁**，但不再是唯一手段。

#### E. ★ 门禁接线（2026-10-11 晚，v0.2.5）

D 建成的三层一度是**"建好但没有调用点"**——`costcontrol.require()` 全项目零调用，付费正文读取实际只靠"是否配了 `JUSTONEAPI_TOKEN`"授权。现在唯一的付费调用点（`research_v2.enrich` 的正文补读）**逐次**走门禁：

| 环节 | 行为 |
| --- | --- |
| 选读取器 | 有 token **且**声明了信封 → `JustOneApiAdapter`；缺任一项 → 免费片段读取器，原因写进 `collection.limitations` |
| 调用前 | `require({DETAIL_V1: 1}, 品牌 × 期信封)` → 先写 `reserve` 行（`channel='rest'`） |
| 调用后 | `settle(reservation_id, code=<业务码>)` → `code=0` 计费，其余按 ¥0 结算 |
| 缓存命中 | **不预留、不结算**（缓存命中不是调用，为它记账就是凭空收费） |
| 额度不足 | 本轮停止，后续目标标 `budget_denied`，写入 `collection.errors` |

**信封只从环境变量来**：`SIGNAL_DESK_SPEND_LIMIT_CNY`（可选 `SIGNAL_DESK_SPEND_LEDGER`）。**未声明即不花钱**——**"有 token" 与 "被允许花钱" 必须分开**。

接线暴露并修掉三处**只在真接线时才显形**的问题：

1. **结算不释放预留**：`remaining` 原先只减 `reserve` 行 → 一次失败调用**永久占住**额度，一个月的失败足以把信封耗空而实际零支出。新增 `consumed()` ＝ 已结算实际值 ＋ 未结算预留估算值；未结算的预留照旧占用（防双花不减弱）。`reconcile()` 仍用 `reserved()`（估算值）对照账单——**两个函数回答不同问题，故不合并**。
2. **业务码藏在错误文案里**：`settle(code=...)` 拿不到码就只能按预留额多记失败调用。新增 `providers.ProviderError`，显式携带 `code`／`http_status`（靠解析文案取码"能用，直到文案被改写"）。
3. **参数名撞车**：`enrich` 内既有的 `ledger` 是**源账本列表**，若把花费账本也叫 `ledger` 会被直接覆盖（首轮实现即踩中，表现为 `TypeError: ... not 'list'`）→ 参数定名 **`spend_ledger`**。

**仍在外面的路**：MCP 侧（本机直调 `call_endpoint`）不走本账本，只能靠"同一个信封"的人工约定。**门禁保护的是管线，不是账户。**

#### F. ★ 配方从"报价"变成"额度"（2026-10-11 深夜，v0.2.6）

**问题不是"配方算错了"，而是配方**从未被核对过**。`RECIPE_CALLS` 自建立以来只服务一个函数——`quote_recipe()`。它能报出"一次 Scan 最多 ¥0.20"，却**不约束任何一次运行**：所有计划的额度都来自同一套 `BUDGET_DEFAULTS`，于是一根打算读 12 条正文的探针，可以被报成 ¥0.55 的 Scan。**报价与执行之间没有连接**。

把模式提到执行层时，两者第一次被并排放在一起核对，**立刻出现两处不一致（都在最便宜的那一档）**：

| 配方项 | 原值 | 依据 | 现值 |
| --- | --- | --- | --- |
| Scan 的检索次数 | 1 | §3 要求计划**至少含一条挑战查询** ＋ 一条定向查询 → 1 次检索的 Scan **连计划都过不了**（`planning_errors`） | **2** |
| Scan 的正文读取 | 0 | §4 说 Scan 产出"**在用的词**"，§2.2 明令 ≤60 字符摘要**不可用于语言复用** → 不取正文的 Scan **产不出它声称的产出** | **1** |

→ `scan` 上限由 **¥0.20 改为 ¥0.55**；`probe`（¥0.85）与 `frame`（¥1.50）经同一核对**无需改动**。

**改动本身很小，方式更重要**：额度不再另写一套数字，而是从同一张配方表派生——

```python
RECIPE_ALLOWANCES = {mode: {'queries': recipe[SEARCH_V4], 'body_reads': recipe.get(DETAIL_V1, 0)}
                     for mode, recipe in RECIPE_CALLS.items()}   # 导入时解析一次
```

> **为什么必须"导入时解析一次"**：若在调用时按端点常量去查表，那个查询会跟随常量的**当时值**——把 `DETAIL_V1` 指向一个配方里没有的版本号，`body_reads` 会**静默变成 0**，而这看起来完全像是"有意不买正文"。**零额度是一种政策声明，不能有意外到达它的路径**（与 §2.8 D 规则 1 同构）。此点由 `tests/signal_desk/test_modes.py::test_allowances_do_not_follow_a_later_change_to_the_endpoint_constants` 锁死。

**花费按模式可分账**：一个信封覆盖同一品牌同一期的所有模式，所以每笔预留带上 `mode`，`report()` 增加 `by_mode`／`spent_by_mode`，并可按模式过滤金额（**上限仍是信封的，不被模式切分**）。没有这个标记，"Frame 的真实成本是不是 ¥1.50"在账本上无法被回答——而修正配方的唯一依据，就是真实成本。

~~**仍待裁定**：模式与任务不匹配时是**提示还是阻断**~~ → **✅ 已裁定（2026-10-12，方法论 §4.2／§9.2 第 15 项）**：**分关口处理**——批准关口上升为契约不合格项（须换模式或显式接受更弱交付）、定时配置关口**硬拒保存**、执行关口保持提示不阻断。**每类任务的默认模式建议并入 pre-flight 体检，不单独立项**。均**待实现**。


---

### 2.9 ★ 官方文档核对（2026-10-11，来源：`https://docs.justoneapi.com/zh/usage`）

把上一轮所有关于计费的说法对官方使用指南逐条核对。**结论：此前的三条推断全部被官方确证，另发现一条我们完全没建模的配额轴。**

#### A. ✅ 计费规则表（官方原文表格转录）

只有 `code=0` 计费：

| `code` | 含义 | 是否计费 |
| --- | --- | --- |
| `0` | 成功 | **是 💰** |
| `100` | Token 无效或已失效 | 否 |
| `301` | 采集失败，请重试 | 否 |
| `302` | 超出速率限制 | 否 |
| `303` | 超出每日配额 | 否 |
| `400` | 参数错误 | 否 |
| `500` | 内部服务器错误 | 否 |
| `600` | 权限不足 | 否 |
| `601` | 账户余额不足 | 否 |
| `602` | TOKEN 限额超限 | 否 |

**已转录进代码**：`costcontrol.BILLING_CODES`（`BILLING_CODES_VERSION = 'justoneapi-usage-20261011'`），并提供 `is_billed(code)`／`code_meaning(code)`。`settle()` 现在接受 `code=` ——**失败调用自动按 ¥0 结算，而不是按预留额结算**。

> **两处 fail-closed 方向相反，且必须相反**：
> - **报价**：查不到单价 → **拒付**（"看不清就不花钱"）。
> - **计费码**：遇到未知 code → **视为已计费**（"看不清就不敢假设免费"）。
>
> 两个方向都指向同一个目标——**绝不悄悄少算钱**。未知 code 多算的成本会在 `reconcile()` 里以 variance 暴露，而少算则永远不会被发现。

#### B. ✅ 令牌上限是"令牌级"，官方原句确认

> `601` 表示账户共享余额不足。`602` 表示当前 API TOKEN 自身的累计消费上限已达到。**TOKEN 限额不是资金划拨，多个 TOKEN 仍共享同一个账户余额。**

这**直接确证**了 §0 第 9 条的判断：`budgetAmount` 只约束绑定此令牌的通路，账户余额是共享的。也再次说明为什么账本（而非控制台上限）才是防双花的正确位置。

#### C. ⚠️ 新发现：还有第二条配额轴（**我们没建模**）

官方原文：

> 管理员可能会按"**用户 × 接口**"为账户配置**每日成功请求限额**；未配置时不限制。每日限额按 `Asia/Shanghai`（UTC+8）自然日计算：**同步请求归入请求发起日，异步任务归入任务提交日**。**同一账户下所有 TOKEN 的请求合并计数**，仅业务返回 `code=0` 的成功请求计入限额。
> 达到每日限额后，该接口会返回业务码 `303` 和 HTTP 状态码 `429`，**超限请求不会计费**。

三个要点：

1. **额度不止"钱"一个维度，还有"每日成功次数"维度。** `Envelope` 只建模了货币，所以一个方案**可能通过金额校验、却在调用的那一刻被上游拒掉**（`303`）。
2. **计数口径是跨 TOKEN 合并的**——与 B 的"共享余额"是同一枚硬币的两面，"两条通路各算各的"这个假设在**限额维度上同样不成立**。
3. **日期归属有规则**：同步请求算发起日、异步任务算提交日。这对 `Envelope.period` 的跨日语义有影响——~~现有 `period` 是个自由字符串，**未定义时区与归属规则**~~ → **✅ 部分裁定（2026-10-12）**：**货币轴的期界已定为 `Asia/Shanghai` 自然月**（即 `costcontrol.period_of()` 现行行为，方法论 §9.2 第 14 项）；供应商侧的"同步算发起日／异步算提交日"规则在**次数轴**（第 13 项）上生效，次数轴另按自然**日**。

> **处置（2026-10-12 更新）**：**第二配额轴已裁定纳入费控**（方法论 §9.2 第 9 项）——`Envelope` 增加次数维度，或并行一张日配额表；两轴期界不同（货币＝自然月、次数＝自然日）。**仍未实现**（这是一个新的开工项，不是待决问题）。模块 docstring 中的对应表述已同步更新。

#### D. ✅ 超时建议印证了 pre-call reserve 的必要性

> 建议将请求超时时间设置为 **120 秒**；……这并不代表 API 很慢，而是为了避免由于短暂的网络抖动或客户端超时导致**重复请求或误判错误**。

官方明确把"客户端超时后重试"列为已知风险。**一次超时重试若打在一个其实已成功（`code=0`）的调用上，就是一笔双倍扣款**——这正是 `authorize()` 在调用前先写 reserve 行所要防的场景。原设计理由是"两条通路"，官方文档补上了第二个理由：**"同一条通路的重试"**。

#### E. 接入细节（补上代码通路缺的那块）

| 项 | 值 |
| --- | --- |
| 生产地址 | `https://api.justoneapi.com` |
| 认证方式 | **token 作为 URL 参数**：`https://api.justoneapi.com/your-endpoint?token=your_access_token` |
| 速率限制 | **无通用速率限制**；部分高并发接口另有特定速率（超限 `302`） |
| 官方 SDK | `justoneapi-official/justoneapi-python` |
| 官方 MCP | `justoneapi-official/justoneapi-mcp` |
| 免费额度 | 注册后无需立即充值，先给一定免费调用次数（**本账户已用尽**） |

> `pricing.API_BASE_URL` 已记录该地址。这填上了 §7"代码通路缺 `JUSTONEAPI_TOKEN`"里**"怎么传"**的那一半——只差 token 本身。


---



## 3. 为什么不能"直接复用 codex 的 token"

codex 把 OAuth 凭证存在 **macOS 钥匙串**，服务名 `Codex MCP Credentials`，账号 `justoneapi|696c3e893ffcce84`（2026-09-08 建立）。结构：

```json
{
  "server_name": "justoneapi",
  "url": "https://mcp.justoneapi.com/mcp",
  "issuer": "https://auth.justoneapi.com",
  "client_id": "joa_dcr_5nW4Mtj4RRMB…",
  "token_response": {
    "access_token": "joa_at_v1_…",  "token_type": "bearer",
    "expires_in": 3599,             "refresh_token": "joa_rt_v1_…",
    "scope": "mcp:api:call mcp:account:read mcp:catalog:read"
  },
  "expires_at": 1791703958000
}
```

| 复用方式 | 可行性 | 原因 |
| --- | --- | --- |
| 把 `access_token` 写进 mcp.json 静态 header | ❌ | **寿命仅 3599 秒**，一小时内失效 |
| 把 `refresh_token` 写进 header | ❌ | 不是 Bearer，需 OAuth 刷新流程才能换 access_token |
| 让 WorkBuddy 自己走 OAuth | ✅ **已采用并成功** | 同账号同余额；客户端自动刷新，无需人工干预 |
| 控制台取静态 API Token 放 header | ✅ 备选 | 长期有效，但需人工从 dashboard 复制，且明文落盘 |

**刻意未做**：用 codex 的 `refresh_token` 跑刷新测试。多数 OAuth 服务刷新时**轮换** refresh_token，会让现有可用的 codex MCP 静默失效。C 方案不需要此 token，无需冒风险。

---

## 4. 客户端授权记录（已完成）

| 步骤 | 状态 |
| --- | --- |
| 1. 左侧边栏 **专家·技能·连接器** → **连接器** 页签 | ✅ |
| 2. 右上角 **自定义连接器** | ✅ |
| 3. 对 `justoneapi` 点 **信任** | ✅ |
| 4. 首次调用触发浏览器 PKCE 授权（`auth.justoneapi.com`） | ✅ |
| 5. 凭证由 WorkBuddy 维护并自动刷新 | ✅ 生效中 |

授权 scope 三项：`mcp:catalog:read`（目录）／`mcp:api:call`（调用）／`mcp:account:read`（余额用量）。

### 4.1 故障处置（备用）

| 现象 | 处置 |
| --- | --- |
| 返回 `403 Error 1010` | UA header 未生效或被覆盖 → `headers` 补 `Accept-Language`、`Accept` 等浏览器头 |
| 返回 `401` 但无授权引导 | 改静态 Bearer：`headers` 加 `"Authorization": "Bearer <控制台 API Token>"`（dashboard.justoneapi.com 的 `Default` 令牌） |
| 连接成功但工具为空 | 检查 `mcp-tool-list.json` 是否出现 justoneapi 条目 |
| OAuth 令牌失效 | 在连接器页对 `justoneapi` 重新授权（无需删配置） |

---

## 5. 体检工具

`scripts/justone_mcp_probe.py`（**只调用免费工具，硬拒 `call_endpoint`**）：

```bash
PY=/Users/mikawang/.workbuddy/binaries/python/versions/3.13.12/bin/python3
cd ~/Documents/GitHub/InsightBot-signal-desk

$PY scripts/justone_mcp_probe.py ping       --from-codex-keychain   # 连通性
$PY scripts/justone_mcp_probe.py balance    --from-codex-keychain   # 余额
$PY scripts/justone_mcp_probe.py usage      --from-codex-keychain   # 用量与预算告警
$PY scripts/justone_mcp_probe.py platforms  --from-codex-keychain   # 平台×端点数
$PY scripts/justone_mcp_probe.py endpoints "小红书笔记搜索" --platform xiaohongshu
$PY scripts/justone_mcp_probe.py schema xiaohongshu.search_note_v4

# 或直接用控制台令牌
$PY scripts/justone_mcp_probe.py balance --token <API_TOKEN>
```

令牌来源优先级：`--token` > 环境变量 `JUSTONEAPI_MCP_TOKEN` > `--from-codex-keychain`（只读钥匙串）。

**已实测通过**：

```
MCP 连通 · server=justoneapi-mcp v2.0.0 · protocol=2025-06-18
余额 56.35 CNY（预留 0）
令牌 Default · 状态 VALID · 默认令牌 True
预算上限 None · 已用 0 · 累计消费 0.0000 CNY
⚠ 未设预算上限，建议在控制台设置以防超支
```

**局限**：`--from-codex-keychain` 不做刷新——codex 的 access_token 约 1 小时后失效（返回 401），届时改用 `--token`。这是刻意设计（见 §3）。**WorkBuddy 会话内不需要此脚本**，MCP 工具已原生可用。

---

## 6. 成本核算（v5 按**官方确证单价**重算）

> **本版变更**：全部单价由"余额差分推测值"改为**官方价目表确证值**。最大变化是 `get-note-detail/v1` 从"≤¥0.10／未观测到扣费"改为 **¥0.15**——**成本模型整体上调约 50%**。§2.6 已解释误判根因（异步结算）。

### 6.1 单次研究链成本

| 动作 | 官方单价 | 数量 | 小计 |
| --- | --- | --- | --- |
| `search-note/v4`（一页，17 条） | ¥0.20 | 1 | ¥0.20 |
| `get-note-detail/v1`（取正文） | **¥0.15** | N | **¥0.15×N** |
| `get-note-comment/v2`（取评论） | **¥0.15** | M | **¥0.15×M** |
| **纯检索（不取正文）** | — | — | **¥0.20／页** |
| **检索 + 全部取正文（N=17）** | — | — | **¥2.75／页** |

对应 `costcontrol.py` 的三条配方上限（**v7 起同时是执行层的额度来源**，见 §2.8 F）：

| 配方 | 调用构成 | 上限 |
| --- | --- | --- |
| `scan` | `search-note/v4` ×2 ＋ `get-note-detail/v1` ×1 | ¥0.55 |
| `probe` | `search-note/v4` ×2 ＋ `get-note-detail/v1` ×3 | ¥0.85 |
| `frame` | `search-note/v4` ×3 ＋ `get-note-detail/v1` ×6 | ¥1.50 |

### 6.2 与千瓜的对照（同一任务）

| 场景 | 千瓜 | JustOneAPI |
| --- | --- | --- |
| 单品牌单期：1 关键词 × 1 页 + 取 10 条正文 | 笔记搜索额度 4000／月（充裕）但**正文不可得** | ¥0.20 + 10×0.15 = **¥1.70** |
| 长时段趋势：3 个月 × 4 关键词 × 3 页 | 额度可支撑，但 `noteTime` 精度问题同样存在 | 36 页 ≈ **¥7.20**（不取正文） |
| 评论分析 | **评论搜索 15／月，已耗尽** | ¥0.15×M（无月限） |

**结论**：余额 ≈ **¥55.60** ≈ **278 次搜索** 或 **约 20 条完整研究链**（1 页检索 + 17 条正文）。按项目节奏充值即可的变动成本结构，无月度归零压力。

> ⚠️ **千瓜的"免费"是假象**：千瓜席位是**固定成本**，且 §2.8 B 已证它**根本给不出正文**——所以"用千瓜省 JustOneAPI 的钱"这个想法不成立，能省的只有**摘要级**调用。正文只能付费买。

### 6.3 触发预算管理的阈值

| 若… | 则应… |
| --- | --- |
| 单品牌单期调用 > 20 次 | 走 `costcontrol.authorize()` 开信封（已可用），而非依赖控制台手工设限 |
| 需要长时段全量抓取（> 100 页） | 与千瓜席位成本对比后再决策 |
| 需要蒲公英投放数据 | 小红书蒲公英侧 16 端点已在价目表内，**按 ¥0.10—¥1.50 分档计价**（不再"未测"） |
| 要跑非小红书平台 | 价目表已覆盖 35 平台；用 `pricing.cheapest(platform)` 选端点，避免误用高价档 |

---

## 7. 缺口清单

| 缺口 | 状态 |
| --- | --- |
| WorkBuddy 侧接线 | ✅ **已落盘 + 已授权 + 已端到端验证** |
| 独立 CLI | 🟡 官方无；`justone_mcp_probe.py` 覆盖体检需求 |
| 令牌未配置（代码通路） | ❌ 仍缺 `JUSTONEAPI_TOKEN` — `live` 模式跑不起来（**MCP 通路已可用，与代码通路是两条独立路径**） |
| 单价 | ✅ **已由官方价目表确证**（§2.8 A）；detail **¥0.15**，此前推测值已作废 |
| 预算上限 | ✅ **已设**（2026-10-11）：令牌 `SignalDeskTest`，`budgetAmount 10.9`／`remainingAmount 10`。⚠️ **令牌级而非账户级**，见 §0 第 9 条 |
| 余额/用量本地视图 | ✅ 已由体检脚本覆盖 |
| **适配器版本过旧** | ✅ **已修**：`search-note/v2` → **v4**，参数名同步改（§2.7 A） |
| **证据等级口径** | ✅ **已收敛为单一真源**：`grades.py` 承载八等级 + alias 归一 + **未知等级 fail-closed**（§2.8 C）；四个调用点全部接入。**"两套词表并存但未打通"这一状态已终结。** |
| **千瓜正文能力** | ✅ **已定性（且为否定结论）**：`note.search_by_url` 实测 40 字段无任何内容字段 → `qiangua_body` 是幻影等级，千瓜最高只能到 `note_segment`（§2.8 B）。**`note_body` 唯一来源＝JustOneAPI detail 接口。** |
| **费控/额度中台** | ✅ **已落地并接线**：`pricing.py`（报价）+ `costcontrol.py`（门禁 + 账本），35 项测试通过（§2.8 D／E）。付费正文读取**逐次走 `require()` → `settle(code=)`**；信封由 `SIGNAL_DESK_SPEND_LIMIT_CNY` 声明，**未声明即不花钱**。⚠️ 仍在外面的路：MCP 直调不走本账本 |
| **计费规则** | ✅ **已由官方文档确证并转录进代码**：`costcontrol.BILLING_CODES`（只有 `code=0` 计费），`settle(code=...)` 可按业务码结算（§2.9 A） |
| **第二配额轴（每日成功请求限额）** | ⚠️ **已裁定纳入、未实现**（2026-10-12，方法论 §9.2 第 9 项）：官方存在"用户 × 接口"每日成功次数上限（`Asia/Shanghai` 日、跨 TOKEN 合并计数、超限 `303`+429 不计费）。`Envelope` 只表达货币 → 可能过金额校验却被上游拒。**新开工项**，见 §2.9 C |
| **代码通路接线细节** | ✅ **已明确**：`https://api.justoneapi.com`，token 走 **URL 参数** `?token=...`（§2.9 E）。仍缺 token 本身 |
| Mac mini 未核验 | ❌ 本次只盘主力机；`mcp.json` 与 OAuth 登录**需在 Mac mini 上各自做一次** |
| 多 query 未落地 | ❌ `workspace.py:137` 只取 `queries[0]` |
| 两条通路共用余额 | ✅ **代码通路已生效（2026-10-11 深夜，v6）**：MCP（OAuth）与 REST（env token）**共享同一余额池**，`costcontrol` 的 pre-call `reserve` 已在 `research_v2.enrich` 逐次 `require()` → `settle(code=)` 上真正接线（防双花）。⚠️ **仍在外面的路**：MCP **直调**（人工探针）不走本账本，只能靠同一信封的人工约定 |
| `total` 字段语义 | ⚠️ v4 实测 `total: 17` 但 `has_more: true`，疑非结果总数。**Mika 已裁定：保留现状，下次再验证**（§2.7 注） |
| 价目表时效 | ⚠️ 快照日期 2026-10-11，`pricing.EXPORTED_AT` 已记录导出时点；**价目变动时需重新导出并比对**，不得就地手改 CSV |

---

## 8. 复核方法

```bash
# 1) codex 侧 MCP 是否仍注册
grep -A2 'mcp_servers.justoneapi' ~/.codex/config.toml

# 2) codex 侧 skill 是否仍在
ls ~/.codex/skills/justoneapi-social-listening/

# 3) WorkBuddy 侧接线
cat ~/.workbuddy/mcp.json
grep -c justoneapi ~/.workbuddy/mcp-tool-list.json   # 预期 >0 表示已加载

# 4) 连通性与余额（只读；WorkBuddy 会话内可直接调 MCP 工具）
python3 scripts/justone_mcp_probe.py ping  --from-codex-keychain
python3 scripts/justone_mcp_probe.py balance --from-codex-keychain

# 5) 项目接线是否仍完整
grep -rn 'JUSTONEAPI_TOKEN\|justone_search' insightbot/signal_desk/ | grep -v __pycache__

# 6) v4 解析与证据等级（离线，零成本，不耗余额）
python3 scripts/check_v4_parser.py

# 7) 端点契约实时探测（版本号会漂移，禁止写死）
#    会话内调用 MCP: get_endpoint_schema(xiaohongshu.search_note_v4)

# 8) 价目表与费控（离线，零成本）
.venv-signal-desk/bin/python -c "from insightbot.signal_desk import pricing as p; print(p.table_summary())"
.venv-signal-desk/bin/python -c "from insightbot.signal_desk import costcontrol as c; print({r: c.quote_recipe(r) for r in ('scan','probe','frame')})"
#    信封试跑（只写本地账本，不产生任何真实调用）：
#      env = c.Envelope(scope='demo', period='2026-11', limit_cny='2.60')
#      c.authorize(c.RECIPE_CALLS['frame'], env, run_id='smoke', channel='mcp')
#    注：channel 只能取 'mcp' / 'rest'（对应两条通路，账本据此分开统计并防双花）
#    注：report(scope, period, limit_cny) 三个参数均必填

# 9) 全量测试（真实运行，不再跳过）
env -u PYTHONPATH .venv-signal-desk/bin/python -m pytest tests/signal_desk -q -p no:cacheprovider
#    注 1：**必须 `env -u PYTHONPATH`**。WorkBuddy CLI 会向 shell 注入
#          /Applications/WorkBuddy.app/.../cli/vendor/shim（sitecustomize.py），其 broker
#          拦截 `Path.mkdir`：对"已存在的路径"（`exist_ok=True` 的合法幂等 mkdir）回
#          EEXIST 并抛 PermissionError，**不按标准库语义吞掉**。实测（2026-10-12）：
#          test_scheduling_v2 ×5 ＋ test_workspace_v2 ×2 **间歇性假失败**（同一代码
#          几分钟内先 402+1 后 7 failed，随 broker 是否应答而波动）；kestra PID 测试在
#          shim 下**稳定失败**、摘掉 shim 即通过 → **"既有失败"实为环境噪声，不是代码
#          缺陷**。历史上"默认临时目录被拦成 169 个 setup error"也是同一 shim。
#    注 2：摘掉 shim 后系统默认临时目录即可用，**`--basetemp` 纪律随之作废**
#          （它原本就是为绕开 shim 才存在的）。真基线：**403 passed, 0 failed**。
#    注 3：`-u PYTHONPATH` 仅用于跑测试（等价 CI 环境）；其余用途是否需要 shim 由
#          沙箱策略决定，不要照抄到别的场景。

# 10) 计费码表（离线）
.venv-signal-desk/bin/python -c "from insightbot.signal_desk import costcontrol as c; print(c.code_meaning(301), c.is_billed(301)); print(c.BILLING_CODES_VERSION)"

# 11) 花费信封（门禁的开关本身，离线）
.venv-signal-desk/bin/python -c "from insightbot.signal_desk import costcontrol as c; print(c.envelope_from_env('demo'))"
#    未打印任何信封 = 本机未声明额度 = 正文补读只走免费片段读取器（安全降级，不报错）
SIGNAL_DESK_SPEND_LIMIT_CNY=2.60 .venv-signal-desk/bin/python -c "from insightbot.signal_desk import costcontrol as c; print(c.envelope_from_env('demo'))"
#    注：可选 SIGNAL_DESK_SPEND_LEDGER 指定账本位置（默认 data/signal-desk-spend.jsonl，已 gitignore）
```

**权威来源（两个，都需登录/公开各异）**：

| 用途 | URL | 可达性 |
| --- | --- | --- |
| 价目表 | `https://dashboard.justoneapi.com/zh/dashboard/pricing` | ⚠️ **需登录**，匿名访问重定向。唯一官方价目来源 |
| 使用指南（计费规则／错误码／限额／超时） | `https://docs.justoneapi.com/zh/usage` | ✅ 公开可读 |
| 官方 SDK | `https://github.com/justoneapi-official/justoneapi-python` | ✅ |
| 官方 MCP | `https://github.com/justoneapi-official/justoneapi-mcp` | ✅ |

> ⚠️ **原"既有失败"记录已更正（2026-10-12）—— 实为环境噪声，不是代码缺陷。**
> 原文保留：`tests/signal_desk/test_kestra_runtime_poc.py::test_stop_never_signals_pid_reused_by_another_service` 失败，该测试与 `scripts/signal-desk-kestra-runtime.py` 均与 HEAD 一致（来自 `9fd9ab9`）、只依赖 stdlib。
> **更正依据**：同一测试在 `env -u PYTHONPATH`（摘掉 WorkBuddy CLI 注入的 `sitecustomize.py` shim）下**稳定通过**；同批还有 `test_scheduling_v2` ×5、`test_workspace_v2` ×2 出现**间歇性假失败**。根因＝shim 的 broker 拦截 `Path.mkdir`，对已存在路径的合法幂等 `mkdir(exist_ok=True)` 回 EEXIST 并抛 `PermissionError`（不按 stdlib 语义吞掉）。**真基线：403 passed, 0 failed。** 详见 §8 复核方法 注 1。

历史调用证据重放：
- 2026-09-29（codex 侧）：在 `~/.codex/archived_sessions/` 检索 `mcp__justoneapi__call_endpoint`
- 2026-10-11（WorkBuddy 侧）：原始返回在本机 `~/.workbuddy/projects/…/tool-results/mcp-justoneapi-call_endpoint-*.txt`（5 个文件，最大的 563K）
- **可复核样本（已纳入仓库）**：`docs/signal-desk/evidence/justone-search-samples-20261011.jsonl`（77 条）
