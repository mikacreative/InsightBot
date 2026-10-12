# 执行前契约体检（Pre-flight）设计稿 v0.1

> 状态：**设计稿，未实施**。本文不改动任何生产代码、不跑测试、不提交 git。
> 纪律声明：本文的小写标注 ——【代码事实】= 已在仓库源码中核对到的行为，附 `文件:行号`；【架构判断】= 设计取舍，未经实测；凡未经实测的数字或比率，一律标【架构判断，未验证】。
> 单价一律以官方价目表为准（经 `costcontrol` 转录），余额只用于对账；不可核查的量不写成交付结论。

> **裁定记录（2026-10-12，产品负责人）** —— 第八节的三项分歧已裁定：
> 1. **结构性零稿 = fail-closed**：采纳"暂停调度 + 升级"。零稿**不得**落成干净的 `awaiting_review`，须标独立终态并暂停该定时计划。
> 2. **断言阈值与硬拒关口**：采纳"只在 `H == 0` 断言、`H > 0` 仅提示"；并在**定时配置关口**对 `H == 0` **硬拒保存**（对齐 methodology §9.2(15) 的分关口处理）。
> 3. **Envelope 冻结进计划**：采纳"**批准即承诺、之后可审计**"。批准时读到的信封**快照进 `plan['contract']`**，**执行读快照**而非现读 `env`（与本文 §2.3／§7.1 原"执行仍读 env"的暂定写法相反，已按裁定更新）。
> 4. **预测指标"先二元、后概率"**：**未裁定**，保留为待确认（见第八节 4）。
> 5. **`preflight` 与 `plan_hash` 的关系**：**未裁定**（本文 §2.4 提出，原误指向"第七节"，实际无对应条目；现正式列为第八节 5）。
>
> 上述 1—3 已同步进 `METHODOLOGY.md` §4.2 与附录证据声明；代码实现仍**未开始**（本组件目前只有设计稿）。

---

## 结论先行（TL;DR）

1. **本组件是"预测器"，不是把守卫前移。** 证据守卫（`editorial_v2.validate_edition`）留在编辑关口不动 —— 准入规则需要真实证据，规划时还没有证据。前移的只有"守卫会不会被触发"的预测。【架构判断】
2. **系统当前确实没有任何预测能力**：`plan.budget` 是上限不是预测（`BUDGET_CAPS` 封顶）【代码事实，research_v2.py:105】；`collection.summary_only` 是事后计数【代码事实，research_v2.py:1077、:1612】；`plan.limitations` 是**警示语**不是**预报**，且 UI **根本不渲染它**【代码事实，ui_v2.html:116】。
3. **契约三要素在系统里都已有载体**，本设计的重点是**显式聚合**它们（Envelope + mode + delivery_profile + 来源强制守卫），不造新词替代旧物。【架构判断】
4. **可预测性必须诚实分层**：花费上界、层覆盖、配额、交付规格 = **确定性高**（纯函数）；正文可得性、摘要占比、上游命中量、是否通过编辑质量检查 = **不可预测**。设计只用前者下结论。【代码事实 + 架构判断】
5. **零稿风险只做二元判断**：`非摘要证据可达上界 H == 0` → 断言"极高零稿风险"（确定性高）；`H > 0` → 只能说"未知/风险偏高"，**不得给概率**（未验证比率）。该代理指标**已知方向性偏差：低估零稿风险**。【架构判断，未验证】
6. **最关键的现场事实：今天存在"静默零稿"**。零稿交付能通过校验 → 状态落到 `awaiting_review` → 定时调度**不会暂停**（`_finish_scheduled_job` 只在 `failed/interrupted/needs_revision/采集不确定` 时暂停）【代码事实，workspace_v2.py:884、:1024】。**全自动能成立的前提，是先把"结构性零稿"从 `awaiting_review` 里分出来并强制升级**。【架构判断】

---

## 一、要解决什么（问题陈述）

### 1.1 产品形态已定，缺的是它依赖的那块能力

产品形态 = **全自动 + 契约式把关**：人在"批准关口"把关**一次**（是否通过这个任务在【一定预算范围、执行方式、交付标准】内自动化执行），批准后**全自动执行**，守卫全部强制、**无人 override**。保留三类升级：**① 费控预警 ② 无产出预警 ③ 提供选择**。

要让"全自动 + 判断前置"成立，系统必须在**批准那一刻**说得出三个问题的预判：**会花多少、会覆盖到哪些层、会不会白跑（零稿）**。现在一个都答不出来。

### 1.2 为什么现在没有预测能力（逐条对代码）

| 现状 | 代码事实 | 它为什么不是预测 |
| --- | --- | --- |
| `plan['budget']` | `BUDGET_DEFAULTS` 被 `BUDGET_CAPS` 封顶，`mode_budget()` 派生配额【research_v2.py:101-108、:272-285】 | 这是**允许用的上限**，不是**预计会用的量**。上限恒为大，与真实花费无关。 |
| `collection.summary_only` | 事后对 `evidence` 计数【research_v2.py:1077、:1612】 | 事后口径，只有`collect()`/`enrich()` 跑完才有值，批准时不存在。 |
| `plan['limitations']` | 计划返回里带 `missing_primary_layers`、`mode_shortfall` 措辞【research_v2.py:849-853】 | 是**免责声明式的警示语**（"未接入 X 层"），不是带量纲的预报；且见下条。 |
| UI 是否展示 limitations | `renderPlan()` 只渲染 6 行摘要 ＋ assumptions ＋ `planning_errors`，**不渲染 `plan.limitations`**【ui_v2.html:116】 | 计划里的警示语在界面上**看不见**；操作员实际只在采集后从 `renderEvidence()` 读到 `collection.limitations`【ui_v2.html:146】。 |
| 调度是否有升级通道 | 全仓 grep `escalat/notify/预警` 无命中；暂停逻辑只在 `failed/interrupted/needs_revision/uncertain`【workspace_v2.py:884】 | **没有任何升级对象或送达通道存在**。 |

**一句话**：上限（budget）、事后计数（summary_only）、看不见的警示语（limitations）三者都不构成"批准前的预判"。本组件就是补上这个缺失的词：【架构判断】

### 1.3 关键架构约束（不要质疑）

**证据守卫不能前移**。准入规则需要真实证据才能执行，规划时还没有证据。守卫留在编辑关口。能前移的只有**"守卫会不会被触发"的预测**。因此本设计的产出是一个**预测器**。本文所有设计都受此约束。【架构判断】

---

## 二、契约对象设计

### 2.1 三要素在系统里都已有载体（先确认，再聚合）

| 契约要素 | 现有载体（唯一真源） | 代码事实 |
| --- | --- | --- |
| **Envelope（预算范围）** | `costcontrol.Envelope(scope, period, limit_cny)`，来自环境变量 `SIGNAL_DESK_SPEND_LIMIT_CNY`；期界 `Asia/Shanghai` 自然月 | costcontrol.py:170-181、:297-312；methodology §9.2(14) |
| **mode（执行方式）** | `plan['mode']` + `plan['mode_definition']` + `plan['mode_layers']` + `plan['structure']`（随计划冻结） | research_v2.py:836-842 |
| **delivery_profile（交付标准）** | `plan['delivery_profile'] = dict(DELIVERY_DEFAULTS)` | research_v2.py:848、:119-122 |
| **来源强制守卫** | `plan['source_config']`（`qiangua` 恒为 True，显式关闭会 raise）；编辑守卫按证据等级分流出处 | research_v2.py:816-818；editorial_v2.py:297、:306-311 |

**已有载体，所以契约不新造词汇**。契约对象只是把上述四者**显式聚合**成一份"任务契约"，并补上两份**目前缺失**的字段（见 2.3）。【架构判断】

### 2.2 契约对象的字段清单（推荐形态）

推荐：在 `plan` 内新增一个**派生只读对象** `plan['contract']`，与 `plan['preflight']`（第三节的预测）并列。

```
plan['contract'] = {
  'version':            <契约结构版本>,
  'envelope': {                       # ★ 现状缺失：见 2.3
      'scope':   <brand_id>,
      'period':  <'YYYY-MM'>,
      'limit_cny': <Decimal→str>,
      'source':  'env' | 'plan',      # 该信封从哪读到
  },
  'mode':               plan['mode'],             # 引用，不复制
  'mode_layers':        plan['mode_layers'],
  'structure_intent':   plan['structure'],        # 本轮将尝试的结构层读取
  'allowances':         plan['budget'],           # queries/body_reads/... 冻结值
  'delivery_profile':   plan['delivery_profile'],
  'source_guards': {
      'qiangua_mandatory': True,                  # 现状即强制
      'evidence_floor':    '非摘要证据 ≥ 1 条 / 卡片',   # ★ 显式化现存的隐式守卫
  },
}
```

**为什么是聚合而不是替换**：三要素各自的"唯一真源"仍在 `costcontrol` / `plan['mode']` / `DELIVERY_DEFAULTS` / `source_config`；`contract` 只做**索引与快照**，避免出现"契约里的 mode"和"真实的 mode"两个值 —— 这正是本项目反复避免的那类分叉。【架构判断】

### 2.3 哪些复用现有字段、哪些必须新增

**复用（不新增）**：
- `plan['mode']` / `mode_definition` / `mode_layers` / `structure` / `budget` / `delivery_profile` / `source_config` / `task_type` / `layers` / `limitations`。【代码事实，research_v2.py:821-854】

**必须新增（因为现状确实没有）**：
1. **`contract.envelope`** —— 今天信封**不在计划里**。`enrich()` 在执行时用 `costcontrol.envelope_from_env(plan['brand_id'])` 现读【代码事实，research_v2.py:1398-1401】。这意味着**"批准时的预算范围"与"执行时的预算范围"是两个时刻读的值**，中间可以被改。契约式把关要求批准即承诺，因此需把信封**快照进计划**。【架构判断】
   **✅ 已裁定（2026-10-12）：采纳"批准即承诺、之后可审计"** —— 信封快照进 `plan['contract']`，**执行读快照**（不再现读 `env`）。即：门禁的 `Envelope` 改为从冻结快照构造，而不是每次从环境变量现取。**未实现。**
2. **`contract.source_guards.evidence_floor`** —— `summary_only` 守卫今天是编辑阶段的**隐式**行为（`all(summary_only support)` → 报错）【代码事实，editorial_v2.py:297】。契约需要把它**显式写成一条准入标准**，否则"交付标准"只有字数这类表层约束，没有证据底线。【架构判断】
3. **`plan['preflight']`** —— 预测对象本身，见第三节。

### 2.4 存哪：计划字段内 vs 独立对象

**结论：存在计划内（`plan.contract` / `plan.preflight`），不建独立顶层对象。**
- 理由一：计划已经是"冻结 + 校验和 + 确认"的既有载体（`executePlan` 提交 `plan.checksum`【ui_v2.html:120】；`confirm` 校验 checksum）。契约与预测跟着计划一起冻结，天然满足"批准即承诺"。【代码事实 + 架构判断】
- 理由二：独立对象会引入第二个生命周期的同步问题（契约改了计划没改），与本项目"一个数字一种读法"的纪律冲突。【架构判断】
- 风险：`plan` 参与 `plan_hash`（`collect()` 用它绑缓存，research_v2.py:970）。把 `preflight` 写进 plan 会让 hash 变化 → **旧的 collection 缓存全部失效**。**处置建议**：`preflight` 是纯派生量，**不参与 hash**（计算哈希时排除），或作为 `plan` 的旁挂字段由 API 组装时附加。此点**仍未定**（正式列为第八节 5）。【架构判断】

---

## 三、可预测性清单（含诚实的不可预测项）

### 3.1 能预测的（确定性高，纯函数或环境读取）

| # | 预测项 | 计算依据（可复用） | 确定性 | 出处 |
| --- | --- | --- | --- | --- |
| P1 | **花费上界（一轮模式配方成本）** | `costcontrol.quote_recipe(mode)`：scan ¥0.55／probe ¥0.85／frame ¥1.50 | **高**（价目表已确证） | costcontrol.py:338-347；methodology §6.3 |
| P2 | **调用配额** | `mode_budget(mode)`：queries／body_reads／structure_reads | **确定** | research_v2.py:272-285 |
| P3 | **层覆盖缺口（两类，措辞必须分开）** | `missing_primary_layers(task)`（管线没读取器）／ `mode_shortfall(mode, task)`（模式不采该层） | **确定** | research_v2.py:248-252、:304-314 |
| P4 | **结构层读取清单（免费）** | `mode_structure_reads(mode)` ∩ 已实现（brand SOV／达人金字塔／检索词序列） | **确定**（清单） | research_v2.py:155-164、:75-88、:842 |
| P5 | **信封余量** | `costcontrol.report(...)['remaining_cny']`（consumed-based） | **高**（本地账本，估算） | costcontrol.py:457-488、:256-277 |
| P6 | **是否持有付费读取许可** | `envelope_from_env(...) is not None` ＋ token 存在性 | **确定** | research_v2.py:1398-1406 |
| P7 | **交付规格上限** | `delivery_profile`（max_cards ≤ 3、各字段字数） | **确定** | research_v2.py:119-122 |

> **为什么 P5 标"高"而不是"确定"**：账本是本地估算，供应商异步结算（methodology §6.6 要点 4），故是估算而非真值；对账靠余额差分。这正是本项目"余额只用于对账"的纪律。

### 3.2 不可预测的（必须显式标注，不得假装有数）

| # | 不可预测项 | 为什么不能预测 | 出处 |
| --- | --- | --- | --- |
| U1 | **实际能取到多少正文** | 每次付费正文读取可能返回 `note_meta`（无文本）→ `text_available=False`；无 token 或未声明信封时回退免费片段读取器 → 永远停在 `note_segment`（摘要） | research_v2.py:1484-1486、:1404-1406 |
| U2 | **摘要占比 `summary_only` 的实际比例** | 只有采集后计数；批准时证据还不存在 | 代码事实，research_v2.py:1077、:1612 |
| U3 | **千瓜检索命中量／样本质量** | 依赖实时索引；可能返回 0 条（`status='empty'`） | research_v2.py:1067 |
| U4 | **结构层是否真有数据点** | `survey()` 可能返回"此时段没有数据点"或品牌未收录 | research_v2.py:1260、:1244 |
| U5 | **候选能否通过六项编辑质量检查／数字回溯** | 依赖模型输出与取证文本 | editorial_v2.py:321-328 |
| U6 | **上游"每日成功请求限额"是否被撞（303）** | `Envelope` 只建模货币，第二配额轴**已批准但未实施** | costcontrol.py:34-39；methodology §9.2(9) |

### 3.3 由此得到的预测边界（本设计的诚实边界）

- 本组件**只对 P1–P7 下结论**；对 U1–U6 **只表述为"未知"或"风险"**，**不给数字**。
- 唯一能对 U1/U2 方向做的**结构性推断**是：当**付费正文通路不可用**时，"非摘要 L1 证据"必为 0 —— 这是一个**确定性的推论**，构成本组件最有价值的预测（见第四节"无产出预警"，也是零稿风险二元判断的高置信分支）。【架构判断】

---

## 四、零稿风险怎么估

### 4.1 事后口径（可复用的既存量）

`collection.summary_only`（摘要条数）与 `collection.bodies`（正文条数）【代码事实，research_v2.py:1077-1078、:1612-1614】。它们回答"这一轮采到的证据里有多少是摘要"。

### 4.2 真正掐死卡片的那条守卫

编辑守卫：**卡片的全部支持证据若都是 `summary_only`，直接拒绝**（"仅有标题或摘要，不能支持完整判断"）【代码事实，editorial_v2.py:297-298】。
`summary_only == False` 的等级 = `note_body`（付费正文）、`note_comment`（付费评论）、`brand_structure`／`trend_series`（免费，走 `survey()`）【代码事实，grades.py:40-49】。

**推论**：一条 L1 卡片要能成立，必须至少有一条**付费正文/评论**或**免费结构层聚合**作为支持。这是零稿风险预测的物理基础。【代码事实 + 架构判断】

### 4.3 前瞻代理指标：非摘要证据可达上界 H

定义（批准前即可算，纯函数）：

```
H = (付费正文通路可用 ? body_reads 配额 : 0)
  + (付费评论通路可用 ? comment_reads 配额 : 0)
  + |{ r ∈ mode_structure_reads(mode) : r 已实现 }|          # 免费结构层，随 mode 冻结

其中「付费正文通路可用」= 信封已声明(env) 且 该品牌×期余额 remaining > 0 且 token 存在
```

- **H == 0 的分支（高置信）**：对**主证据层依赖 L1 且无免费结构层路径**的任务，H==0 ⇒ 编辑守卫将拒绝**全部**卡片 ⇒ **"本轮不会产出卡片"** 是**确定性推断**。这是本组件唯一敢"断言"的场景。
  - 构成 H==0 的典型条件（任一）：① 未声明 `SIGNAL_DESK_SPEND_LIMIT_CNY`（`enrich` 回退免费片段读取器）【research_v2.py:1398-1406】；② `body_reads`/`comment_reads` 配额为 0【BUDGET_DEFAULTS 中 comment_reads 默认即 0，research_v2.py:102】；③ mode 无可用结构层读取（如 scan/probe 的 `mode_structure_reads` 只覆盖 L3/T 以外的层，而任务主层是 L1）【research_v2.py:155-164】。
- **H > 0 的分支（低置信）**：只能输出**"零稿风险未知/偏高"**，**不得换算成概率**。

### 4.4 置信度低在哪里，以及误差方向（必须写明）

- **低估的来源**：H 是"**能拿到**多少非摘要证据的**上界**"，不是"**实际拿到**多少"。每一次付费正文读取都可能返回无文本（U1），每一次结构层读取都可能返回空数据点（U4），H 把这些**不会兑现的能力也计入了**。因此以 H 推断"能产出"会**偏向乐观**。
- **误差方向结论**：**该代理指标系统性低估零稿风险**（偏乐观）。据此，它的正确用法是：**只在 H==0 时发出强预警；H>0 时不做任何"不会零稿"的承诺。** 【架构判断，未验证】
- **反方向的误差（避免过度自信）**：H>0 也**不能**保证产出——即使拿到非摘要证据，卡片仍需通过数字回溯与六项检查【editorial_v2.py:321-328】。故 H>0 同样不承诺产出。
- **未验证量（不得写成结论）**：正文读取的实际 `text_available` 成功率、`summary_only` 的实际占比、结构层读取的非空率 —— 这些比率**本文不给数字**，需先埋点采集（第六节 MVP 之后）。【架构判断，未验证】

### 4.5 与"合法零稿"的区分（决定是否需要升级）

- **合法零稿**：拿到了非摘要证据，但都不合格（PDD §7.2「全部不合格时零条」）。**不应升级为故障**。【架构判断】
- **结构性零稿**：根本没有非摘要证据（对应 H==0 的落地形态 / `collection.bodies + comments + 聚合 == 0`）。**这才是必须升级的静默失败**。【架构判断】
- 判别式（事后可算）：`cards == [] and (bodies + comments + 结构层聚合证据数) == 0` ⇒ 结构性零稿。

---

## 五、三类预警与升级（触发条件、阈值、载体）

### 5.1 费控预警

**口径：两者都要，但分关口用不同的那一个。**

| 关口 | 口径 | 触发条件 | 为什么用这个 |
| --- | --- | --- | --- |
| 批准时 | **预测超支额** = `quote_recipe(mode) − report.remaining_cny` | `> 0` → 预警"本轮配方上界可能超出信封余量" | 预测**这轮能不能跑完**；确定性高（P1、P5） |
| 执行中 | **信封消耗比例** = `consumed / limit` | 跨过阈值（建议 80%，【架构判断，未验证】） | 回答**这一期还剩多少空间**；与单轮无关 |

- **为什么两个都要**：单轮上界（P1）答的是"这一轮够不够"，消耗比例答的是"这一期还剩多少"。前者是**事前能否执行**，后者是**事后何时该收敛**，两者不可互替。【架构判断】
- **现有强制点**：真正的 fail-closed 已在付费关口 —— `require()` 不足即 `BudgetDenied`，停止后续付费读取并写入 `collection.errors`【代码事实，research_v2.py:1458-1465】。**费控预警是"提前说"，不是新增门禁。**
- **不预测的部分**：实际花费 ≤ 配方上界（正文只对终选取，`enrich` 只针对 `body_reads` 个目标）【research_v2.py:1418】。"实际会花多少"仍是区间 [0, 上界]，**不给点估计**。

### 5.2 无产出预警（"本轮不会产出卡片"）

**宣布条件（分置信度）：**

| 等级 | 条件 | 措辞 | 依据 |
| --- | --- | --- | --- |
| **确定** | `H == 0`（§4.3） | "本轮可获得的非摘要证据为 0：未声明付费正文许可 且 当前模式无可用结构层读取。对本类任务，编辑守卫将拒绝全部卡片。" | 纯函数，可复算 |
| **提示** | `H > 0` 但 `mode_shortfall` 非空 或 主层有 `missing_primary_layers` | "本轮证据强度低于方法要求，产出可能受限。"（**不断言零稿**） | research_v2.py:304、:248 |
| **事后** | `collection.status == 'empty'`（检索 0 条） | "本轮未返回证据。" | research_v2.py:1067 |
| **事后** | `delivery.cards == []` 且**结构性零稿**（§4.5） | 升级为 `empty_delivery`，**不视为干净成功** | 见 5.4 |

- **为什么"确定"级只放在 H==0**：这是唯一有确定性推论的分支（§3.3）。在 H>0 上断言零稿会误伤（第六节 ①）。【架构判断】

### 5.3 提供选择（升级时必须给出的候选动作）

**主要选项＝换模式**，其余并列。每个选项**必须标注它改变了契约的哪一要素**。

| 选项 | 改变的契约要素 | 说明 |
| --- | --- | --- |
| **① 换模式**（scan→probe→frame） | **mode（执行方式）**（连带改 `mode_layers`／结构层读取清单／配方成本 P1） | 主选项。§4 让"判断强度"归模式所有，换模式是唯一直接提升层覆盖的动作。【methodology §4】 |
| ② 加额度（提高 `SIGNAL_DESK_SPEND_LIMIT_CNY` / 充值） | **Envelope.limit_cny（预算范围）** | 直接提高 P5 余量，解锁付费正文通路（把 H 从 0 抬起来）。 |
| ③ 开通付费正文/评论许可（声明信封、配置 token） | **Envelope 存在性（预算范围）** ＋ 付费通路 | 面向 U1 的正解：H==0 的 ① 类成因。 |
| ④ 换任务类型 | **task_type**（间接改变主层需求 → `missing_primary_layers`／`mode_shortfall`） | 例如把 `品牌与竞争` 换成 `内容与沟通`，落到已实现的 L1 上。 |
| ⑤ 收窄议题（改 queries／时间窗） | **计划范围，不属于契约三要素** | **必须诚实标注**：它不改变契约三要素，只改变可采集量与成本；对"层缺口"型零稿**无效**（治不了 H==0）。 |

- **为什么把"换模式"列为主要**：它是唯一改变**判断强度**（§4 归属 mode）的动作；其余要么改钱、要么改题、要么改范围。【架构判断】
- **全自动下不得自动替用户选**：见 5.4。

### 5.4 载体与送达方式

**分关口 + 分通道：**

| 关口 | 预警类型 | 载体（推荐） | 依据 |
| --- | --- | --- | --- |
| **批准时** | 费控预警、无产出预警、提供选择 | `plan['preflight']`（新，随计划冻结）＋ UI 警示区 | 见下"UI 缺口" |
| **执行中** | 无产出（H==0 落地为结构层空/检索空）、费控消耗比 | `collection.limitations`（**已被 UI 渲染**） | research_v2.py:1080-1084；workspace_v2.py:924-925；ui_v2.html:146 |
| **全自动无人值守** | 全部三类 | **持久化升级记录**（计划/调度运行上的 escalation 字段 + 通知外发）＋ **调度暂停** | 现状无任何通道【workspace_v2.py:884】 |

**UI 缺口（必须先补，否则预警无处可看）**：
- `renderPlan()` **不渲染 `plan.limitations`**【代码事实，ui_v2.html:116】。因此 `plan.preflight` 若沿用"写进 limitations"的做法，**在批准关口同样看不见**。MVP 必须在 `renderPlan()` 增加一块**非阻断**的"体检"提示区（与现有 `planning_errors` 区分——后者会 `needs_revision` 阻断，体检结论**不阻断**）。【架构判断】
- `budgetCaps` / `budgetLabels` **缺 `comment_reads`、`structure_reads`**【代码事实，ui_v2.html:70-71】。`renderPlan` 会遍历 `plan.budget` 把它们渲染成输入框，但**标签退化为原始英文键、且没有 `max` 上限**【ui_v2.html:116】。体检要显示"付费通路是否可用"，这两个字段理应有标签与上限。

**全自动场景的处理（本设计的核心难点）：**

1. **必须持久化**：无人看时，预警不能只活在一次 HTTP 响应里。需落到**调度运行记录**（`schedule_runs`）与计划上，作为可审计的升级记录。【架构判断】
2. **fail-open vs fail-closed（分类决定，不一刀切）：**
   - **费控** —— 已 fail-closed（付费关口 `BudgetDenied`）【代码事实】。体检只需提前说，**不需要新增阻断**。
   - **结构性零稿（无人值守）** —— **fail-closed**：不得落成干净的 `awaiting_review`。应标为独立状态（如 `empty_delivery`）并**暂停该定时计划**，理由"本轮无任何非摘要证据，产出为零；已暂停自动执行待人工核对"。**这直接堵上现状的静默零稿（见 1.2 / 5.4-3）。**
   - **合法零稿（有非摘要证据但都不合格）** —— **fail-open**：记录，不暂停。零稿本身合法（PDD §7.2）。【架构判断】
   - **提供选择** —— **不得自动选**。无人时记录选项并**暂停**，绝不自动换模式（换模式等于改了已批准的契约，违反"批准一次"）。【架构判断】
3. **送不到怎么办**：升级记录写盘即为"送达底线"。外部通知（邮件/IM）可作为增量，**不承诺必达**；无论外部通道是否成功，**本地升级记录 + 调度暂停先成立**。理由：本地记录不会丢，外部通知会。【架构判断】

---

## 六、失败模式与误伤

### ① 提前断言"注定零稿"但实际能产出

- **代价**：误伤一个本可产出的任务；最坏情况是**定时任务被误暂停**，用户以为系统坏了。
- **降低办法（分级 + 只警告不阻断）**：
  1. **只对 H==0 用"确定"措辞**；H>0 一律"风险偏高/未知"。【架构判断】
  2. **批准关口默认只警告，不阻断**（`plan.ready` 不受影响）。
  3. **定时配置关口**对 H==0 可**硬拒保存**（对齐 methodology §9.2(15) 的"定时配置关口硬拒保存"建议）——此时改变主意零成本。【架构判断】
  4. 若用户坚持执行，可给一次**显式确认**，并把该确认**冻结进契约**（可审计：批准时已知 H==0）。【架构判断】
  5. **限定断言范围**：H==0 的断言**只对"主层依赖 L1 且无免费结构层路径"的任务成立**；对 `brand_competition × frame` 这类有免费结构层（brand_structure/trend_series）的任务，H>0，**不得断言**。【代码事实 + 架构判断】

### ② 不预警但实际零稿（静默失败）

**现状（必须承认）—— 存在静默零稿：**
- 零稿交付（`cards: []`）能通过 `validate_edition`，状态落 `awaiting_review`【代码事实，editorial_v2.py:416-425；workspace_v2.py:1024-1025】。
- `_finish_scheduled_job` 只在 `failed/interrupted/needs_revision` 或"采集不确定"时暂停【代码事实，workspace_v2.py:884】。零稿**不在其中** ⇒ **定时任务会带着零稿"成功"继续跑**。这就是静默零稿。【代码事实】

**保证全自动下"不会静默失败"的机制（全自动能成立的前提）：**
1. **事后重新分类**：交付完成后，若 `cards == []`，用 §4.5 判别式区分"结构性零稿"与"合法零稿"。
2. **结构性零稿 → 独立终态**（如 `empty_delivery`），并**纳入 `_finish_scheduled_job` 的 `uncertain` 判据** ⇒ 暂停调度 + 写升级记录。
3. **合法零稿 → 如实记录**（不暂停），避免把合法零结果误报为故障（第六节 ① 的反面）。
4. **预测-实际对照**：把批准时的 `preflight`（H、层覆盖）与实际 `collection.summary_only/bodies` 一起落库，**让漏报可被审计**（H 预测 vs 实际零稿），为后续把二元判断升级为概率判断提供数据（需要真实比率，见 4.4）。【架构判断】
5. **不自动重试**：沿用现有"不确定不重试"纪律【research_v2.py:1440-1445】。零稿的处置是**升级给人**，不是自动再跑。

---

## 七、MVP 与后续切面

### 7.1 MVP（只加什么，尽量不引入新概念）

**原则：只用现有纯函数组装一份 `plan['preflight']`，外加两处渲染修复 + 一处终态分类。**

1. **`plan['preflight']`（派生、只读、不阻断）** — 组装现有量：
   - `spend_ceiling_cny = quote_recipe(mode)`（复用 costcontrol）【P1】
   - `envelope_remaining_cny = report(...).remaining_cny`（复用）【P5】
   - `unreadable_primary_layers = missing_primary_layers(task)`（复用）【P3】
   - `mode_shortfall = mode_shortfall(mode, task)`（复用）【P3】
   - `non_summary_capacity H`（**一个小函数**，用 `grades` ＋ `budget` ＋ `mode_structure_reads`；见 §4.3）
   - `zero_risk = 'high' if H == 0 else 'unknown'`（**只两值，不给概率**）
   - 全部标 **[架构判断]**，不新增词汇。
2. **`renderPlan()` 增加"体检"非阻断提示区**（因为 `plan.limitations` 今天不渲染【ui_v2.html:116】）。
3. **`budgetLabels`/`budgetCaps` 补 `comment_reads`、`structure_reads`**（否则原始英文键裸露、无上限【ui_v2.html:70-71】）。
4. **事后结构性零稿分类**：`cards == []` 且无非摘要证据 → 独立终态 → 纳入 `_finish_scheduled_job` 的 `uncertain` → 暂停调度【workspace_v2.py:884】。
5. **`contract.envelope` 快照 + 执行读快照**（裁定 3，2026-10-12）：把批准时读到的信封写入 `plan['contract']`，**执行时从快照构造门禁的 `Envelope`**，不再现读 `env`。⚠️ **这一条比原 MVP 大一圈**：它**改变门禁行为**（批准后被改的 `SIGNAL_DESK_SPEND_LIMIT_CNY` 不再影响该次执行）。原稿写"执行时仍读 env（不改门禁行为）"是当时为了压缩 MVP 范围，现已按"批准即承诺、之后可审计"的裁定更新——**代价换来的是契约的两个时刻真正是同一个数**。同时必须处理 §2.4 的 `plan_hash` 联动（见第八节 5）。

**MVP 明确不做**：连续概率、外部通知外发、选择卡一键换模式、每日次数配额轴、每类任务默认模式建议。

### 7.2 后续（留待决定后再做）

| 项 | 依赖 | 说明 |
| --- | --- | --- |
| 完整 escalation 对象 + 通知外发通道 | MVP 跑出真实数据 | 5.4 的持久化升级记录成型后再接渠道 |
| 零稿**概率**（而非二元） | 需先埋点采集 U1/U2 的真实比率【架构判断，未验证】 | 没有真实比率前不给概率 |
| 每日次数配额轴（303） | methodology §9.2(9) 未实施项 | 第二轴上马后并入费控预警 |
| 每类任务默认模式建议 | ✅ **已裁定（2026-10-12）：并入 pre-flight 体检，不单独立项** | 由本文 §5.3 的"换模式"选项给出，批准关口随体检报告一并呈现 |
| 一键"换模式"选择卡 | UI | 5.3 的选项落到交互 |

---

## 八、分歧点：已裁定与被保留的

### 8.1 ✅ 已裁定（2026-10-12，产品负责人）

1. **全自动下"结构性零稿" = fail-closed** —— 采纳 **`empty_delivery` 纳入 `_finish_scheduled_job` 的暂停判据（暂停定时 + 升级）**，不是"只记录不暂停"。理由：全自动下无人接住零稿，若调度继续跑，系统会**在客户面前安静地失败**（第五节 5.4-2、第六节 ② 的机制据此成立）。**这是"全自动能否成立"的前提条款。**
2. **零稿风险的断言阈值与硬拒关口** —— 采纳 **只在 `H == 0` 断言、`H > 0` 仅提示**（保守、几乎不误伤），并在**定时配置关口**对 `H == 0` **硬拒保存**（对齐 methodology §9.2(15) 的分关口处理）。批准关口仍**只警告、不阻断**（§6 ①）。
3. **Envelope 冻结进计划** —— 采纳 **"批准即承诺、之后可审计"**：信封快照进 `plan['contract']`，**执行读快照**而非现读 `env`。⚠️ 这一条**改变门禁行为**（见 §7.1 第 5 条的更新），因此不是纯增量改动；与之绑定的 `plan_hash` 问题见 8.2 第 5 项。

### 8.2 ⏳ 仍未裁定（保留）

4. **（次要）预测指标是否接受"先二元、后概率"？** 连续概率需要先埋点采集正文 `text_available` 率与 `summary_only` 率（当前**未验证**）；是否同意 MVP 只做二元（H==0 / 未知），把概率留到有真实数据之后？**（本条 2026-10-12 未答，保留。）**
5. **`preflight` 是否参与 `plan_hash`？** 由 §2.4 提出：`plan` 参与 `plan_hash`（`collect()` 用它绑缓存，research_v2.py:970）；若把派生量 `preflight` 写进 `plan`，hash 会变 → **旧 collection 缓存全失效**。两条路：把 `preflight` 排除在 hash 之外（纯派生量不进哈希），或作为 `plan` 的旁挂字段由 API 组装时附加。**（原稿误写为"列入第七节"，第七节并无此条；现正式列在此处。）**

---

## 附：本文引用的代码事实索引

- `research_v2.py:75-89` STRUCTURE_READS / 版本；`:101-108` BUDGET_DEFAULTS / BUDGET_CAPS；`:119-122` DELIVERY_DEFAULTS；`:140-152` MODES / DEFAULT_MODE；`:155-164` mode_structure_reads；`:171-177` IMPLEMENTED_LAYERS；`:248-252` missing_primary_layers；`:272-285` mode_budget；`:304-314` mode_shortfall；`:317-331` mode_limitations；`:416-428` execution_budget；`:792-854` plan() 返回结构（ready / planning_errors / limitations / structure / mode_layers）；`:966-1088` collect（含 `:1077` summary_only 计数）；`:1200-1278` survey；`:1341-1620` enrich（含 `:1612` summary_only 重算、`:1398-1406` 信封与免费回退、`:1458-1465` BudgetDenied 停止）。
- `costcontrol.py:104-119` RECIPE_CALLS / RECIPE_ALLOWANCES；`:170-181` Envelope；`:246-277` reserved / consumed；`:338-347` quote_recipe；`:350-395` authorize / require；`:398-436` settle；`:457-488` report（by_mode / spent_by_mode）。
- `editorial_v2.py:212-367` validate_edition（`:297-298` summary_only 守卫、`:306-311` 出处分流、`:324-328` 数字回溯）；`:392-454` edit（`:398` delivery_profile、`:406-410` enrichment_policy、`:416-425` 零证据路径）。
- `workspace_v2.py:865-886` _finish_scheduled_job；`:895-967` 编排节点（collect→survey→edit→enrich→reedit→validate→human）；`:1024-1025` 终态落 awaiting_review。
- `ui_v2.html:70-71` budgetCaps / budgetLabels；`:116` renderPlan；`:118` planEdits；`:120` executePlan（checksum）；`:146` renderEvidence。
- `grades.py:40-49` 等级表；`:122-148` summary_only / is_note_text / is_body / is_meta。
- `METHODOLOGY.md` §4／§4.1（模式落进执行层）、§6.2（千瓜分档）、§6.3（JustOneAPI 单价）、§6.6（费控中台）、§9.2(9)(15)。
