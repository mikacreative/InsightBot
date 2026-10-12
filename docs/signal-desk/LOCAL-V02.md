# Signal Desk 0.2.1 本机测试

日期：2026-10-07。产品范围以 [PDD](PDD.md) 为准。本轮不发布 Mac mini。

## 当前续接（2026-10-07）

功能主实现基线为 `9fd9ab9`，在 `codex/signal-desk` 继续修复审阅问题。[PR #15](https://github.com/mikacreative/InsightBot/pull/15) 已创建、尚未合并；审阅范围包括独立品牌研究工作区、连续对话、有限补证、本机调度与 Kestra 原型。首轮五项发现及修复验证见文末。

- 本轮本机完整回归为 **662 passed, 6 warnings**，Python 编译及差异检查通过；前端类型检查、构建及启动脚本语法在先前提交前通过。[先前 GitHub PR Test](https://github.com/mikacreative/InsightBot/actions/runs/37624378698) 在 Python 3.12 下为 **390 passed, 9 skipped**；最新提交的 CI 与再次审阅以 PR 为准。9 个模块因 CI 未安装独立 LangGraph 依赖而跳过，不能将 CI 结果解释为完整 Signal Desk 验收。
- 本轮同步时，18876 原工作区与 18977 独立原型健康接口均正常；原型方案为 v8，自动执行暂停，三次验证执行均为 `SUCCESS`。实际 AI 规划、原生定时触发及重启审核恢复的证据见文末；来源样本和发布渠道仍为虚构／模拟。
- 本轮已修复首轮五项审阅发现；下一步核对新提交的 CI 与再次审阅，再以一条真实研究路径接入现有千瓜、精选编辑及审核能力，保留品牌权限、凭据、单轮额度与方案版本。管理员模块目录、真实频道和正式产品迁移仍按 [PDD 第13节](PDD.md#13-可管理研究工作流kestra-本机原型) 分阶段验收。
- 真实供应商研究质量、同议题两期业务试读、长期重复调度与商用可用性仍待验证。千瓜授权已于 2026-10-08 续期，2026-10-11 复核为 fresh（`auth test` 返回 Jessie Zhou，接口权限 7/7 可用）；10-07 的 401 记录不再适用。恢复真实研究前仍需处理文末 2026-10-11 记录的两处链路问题。
- 主工作区 `InsightBot` 的 `main` 有尚未提交的文档改动；继续保留，后续合并使用独立工作树。当前 PR、CI 与本机测试不构成生产部署或品牌数据迁移授权。

## 入口与数据

- 本机：`http://127.0.0.1:18876/`，使用原本机账号登录。
- 代码：`InsightBot-signal-desk` 工作树，分支 `codex/signal-desk`。
- 私有运行目录：`~/Applications/SignalDesk-local/state`；0.2 在其下使用 `v2/` 新命名空间。
- 旧版数据保留；`/legacy` 仅管理员可读，旧写接口关闭。不自动迁移旧研究到新品牌。
- 本地启动：`~/Applications/SignalDesk-local/start.command`。凭证存于同级 `config.env`，不进 Git。

## 试用顺序

1. 管理员创建品牌，配置品牌资料、成员及信号来源。不同品牌资料独立。
2. 选择品牌，直接在对话中描述营销问题。需要补充信息时，回答追问或点击“暂不确定，你先建议”；不回答则保留在当前对话，不自动开始研究。
3. 左侧按品牌列出任务；中间节点图展示研究脉络，点击节点检阅数据来源与方法，也可“手动修改”。右侧继续用自然语言调整。满意后点击“开始研究”，结果保留在任务的执行记录中，未知调用结果或中断不自动重试。
4. 如需自动执行，在任务详情选择一次、每天或每周、具体时间及观察范围，再“保存时间”预览下次执行；也可以在对话里说“每周一早上9点，看上周的讨论”。检查方案与时间后点击“启用自动执行”，随时可暂停。时间均为北京时间；本机服务运行时才会执行，关闭、重启或休眠错过的时间不会补跑。修改方案或时间后需重新启用；失败会暂停后续运行。
5. 从执行记录查看结果，审阅最多3条精选；核对出处、边界与参考用途，必要时修改。通过后导出Markdown。
6. 对结果留下“有参考／已知或重复／依据不足／无关／值得补证”反馈；下一期继承同一议题。

来源以千瓜为主，网站搜索与RSS用于外部背景。背景摘要未核验时不作为主张证据。缺少某来源须在运行说明中显示，不能声称已完成多源核验。JustOneAPI不在0.2默认执行链路中。

新版本的数量与字数限制是服务交付上限，不是必须凑足的篇数。客户稿没有自动派工、预算调整、KPI或排期。

## 运行边界

一次成功运行不能替代两期业务试读或商用验收。千瓜会话过期时需要管理员重新授权；不应在对话中传递Cookie。AI配置已填写也不代表其每次响应都会通过编辑质量检查。测试失败须保留范围与原因，不使用演示内容替代真实发现。

## 2026-10-07 验证与当前限制

- 115项相关测试通过，包含品牌成员隔离、猜测ID、角色提升防护、CSRF、冻结计划与重复执行、重启审核恢复、精选数量及字数、引用与趋势边界、旧工作流和频道回归。既有feedparser弃用警告6条，不影响本轮结果。
- 通过实际HTTP接口检查未登录访问、越权品牌读取、管理员旧记录访问及过期计划拒绝。
- Chrome桌面1440×1000及移动390×844：品牌选择→模板计划；合成稿件读取→人工修改→批准→下载→反馈通过。无页面脚本错误或横向溢出。首次登录恢复品牌／研究深链接已修复并复测。Browser插件未提供，本轮使用已有Playwright与Chrome，没有安装新浏览器。
- 已配置AI以完全虚构文具品牌完成一次规划，生成2组查询、824 tokens；独立精选编辑测试返回零稿并通过协议，未用合成材料冒充真实发现。
- 千瓜轻量鉴权返回401，需要续签；真实千瓜采集及真实品牌AI研究未验收。网站搜索／RSS接入有配置与单元测试，但真实多源完整研究尚未验收。
- 同议题两期继承、反馈和新证据回看通过合成自动化测试；不等于两期业务试读完成。

当前每次批准运行形成一期交付，尚未实现多次运行合并为月度期次或合同核验额度结算。本机时间调度见本文件末尾最新验证记录；各次运行仍受确认的单轮额度约束。交付规格暂固定为PDD试点默认上限。网站／RSS为未核验背景，不能替代主张正文证据。千瓜接口未返回正文时可以零稿，不自动调用JustOneAPI补齐。

本机默认从产品仓库的同级目录定位 `qiangua-insights`，使用同一个Python环境；不同位置可由管理员配置 `SIGNAL_DESK_QIANGUA_REPO` 与 `SIGNAL_DESK_QIANGUA_PYTHON`。品牌管理员在品牌设置中维护RSS URL白名单与网站搜索开关，不复用其他品牌来源配置。

## 0.2.1 入口修正与工作区边界

2026-10-07：开发继续在 InsightBot 独立工作树；新增模块AGENTS约束默认提示与测试中不得挟带单一客户背景。PDD更新为0.2.1，Sun Life仅为一个品牌工作区。聊天本身的既有客户上下文不会被自动清除；后续长期开发宜从此工作树开启独立产品任务。

营销任务入口扩为品牌与竞争、平台运营、商品与卖点、人群与使用场景、内容与传播、数据变化。原有跟踪对象保留，界面改称“跟踪问题（可选）”，不要求首次使用先建议题。品牌资料、凭证、历史研究和数据库结构没有迁移。

### 0.2.1 本机验证（2026-10-07）

- Signal Desk 与频道回归共 129 项通过；6 条 feedparser 弃用提示，无失败。
- 虚构文具问题完成三轮模板规划：自由补充不自动成为关键词，显式关键词形成可核对计划，澄清记录可展开。
- Chrome 桌面与 390px 手机宽度无脚本错误或横向溢出；18876 已重启并验证登录、品牌入口和 0.2.1 页脚。
- 未执行真实客户采集或外部 AI 调用；未部署 Mac mini。真实数据完整试跑仍须另验。

### 2026-10-07：阶段 C 的有限正文补证

本轮从 PDD 继续本机开发，补齐“明确缺口 → 有限补读 → AI重新精选 → 人工审核”的路径。这是阶段C的一部分，尚不代表真实数据及业务试读验收完成。

- 新计划显示“按缺口补证轮次”，默认1、上限1，可改为0后重新确认。开启时先采集列表，将本轮正文额度留给AI指定的缺口；旧冻结计划缺该字段时仍按0轮及原初读方式运行，不迁移历史数据。
- 编辑通过内部 `GAP` 协议说明待研究候选、已有关联证据、具体缺口与预期改变。只允许补读已采集的千瓜标题笔记；不能新建查询、增添来源、指定任意URL或升级网站／RSS摘要为证据。
- 所有正文请求共享计划中的 `body_reads`，相同来源只请求一次。精选、格式修复、补证后重编共同计入执行的 `model_calls`；确认计划前的可选AI规划另存调用记录。没有重编余额就跳过补证并显示原因，不消耗额外来源额度。
- 正文保留原证据ID与标题快照，追加补读记录；规范化与原始URL冲突、笔记ID不匹配、仍无正文、失败及未知结果均不得伪装为补证成功。不自动重试未知请求。
- 界面显示补读／重新精选进度，展开证据后可查看缺口、取舍影响与每份来源的结果。批准与导出仍绑定当前稿件版本；证据不足时保留零稿和范围说明。

验证：Signal Desk 128项、原日报及频道36项，分进程运行共164项通过；编译与 `git diff --check` 通过。保留6条既有feedparser弃用提示。新增25项补证测试包含额度、身份冲突、原子账本读写、中断、零稿与审核恢复。

Chrome／Playwright在独立虚构测试服务 `127.0.0.1:18976` 完成：修改额度并更新确认 → 补证状态 → 证据记录 → 人工修订 → 审批 → 下载 → 反馈与刷新。桌面1440×1000、手机390×844无脚本错误或横向溢出；Browser plugin未提供，使用已有Playwright和Chrome。测试数据与现有品牌目录分开。

本机18876服务已在确认无执行中研究后重启，健康接口及新版页面通过检查。保留原账号与配置。未调用真实数据商或外部模型，未部署远端；正文补证的真实千瓜链路、两期业务试读、网站原文补证、多运行合并期次及合同额度仍待后续验收。

以下为当时分进程复测命令；旧测试的全局依赖替换已在本轮提交前修正，完整测试命令见文末：

```bash
.venv-signal-desk/bin/python -m pytest -q tests/signal_desk
.venv-signal-desk/bin/python -m pytest -q tests/test_channel_rendering.py tests/test_channels.py tests/test_task_runner.py
.venv-signal-desk/bin/python -m compileall -q insightbot scripts
```

### 2026-10-07：连续对话入口与失败恢复

按本轮产品反馈，主入口改为连续 Chatbot 对话：提出问题 → 必要追问／先给建议 → 生成与修改方案 → 手动开始研究 → 查看结果。取消主流程的类型选择与研究／交付标签页；品牌资料、来源和成员管理放入设置。方案只显示必要的方法与数据口径，查询及额度按需展开。

- 回答和修改复用同一任务，逐版保存方案；刷新后恢复完整对话。规划中的请求阻止重复发送，失败内容保留，未处理的修改不能执行旧方案。
- 模型根据最新回答及上一版方案调整问题、查询和日期。没有明确答案时，可使用可见假设；必要问题及范围限制仍须解决。规划不扩大来源权限、不自动增加额度或启动采集。
- 合法但超出本轮额度的提案完整保留为待调整草稿，给出明确原因；不以通用400报错结束，也不静默删查询。设置调整不额外请求模型。
- 检查了本机现有提交记录：最后一次规划已保存有效提案，但3组查询超过2组上限。复用该缓存恢复待调整草稿，并保留用户原回答、此前澄清和原始失败记录；没有重发客户内容或执行研究。

验证：Signal Desk 178项、原日报及频道36项，分进程共214项通过；编译、UI JavaScript语法、`git diff --check`通过。保留6条既有feedparser弃用提示。新增检查覆盖跨品牌对话隔离、连续方案、完整历史、失败及中断恢复、额度超限和新方案与旧研究结果隔离。

使用 Codex in-app browser 和独立虚构测试服务验证：追问与回答、先给建议、自然语言改日期和查询、刷新恢复、超限调整、手动开始、结果阅读、修改批准与反馈。1280×720和1536×1024桌面、390×844手机无脚本错误或横向溢出。模型与数据接口在测试服务中被替代；该交互验证不代表真实供应商研究验收。

界面参考图与实际截图逐项对照：① 顶部品牌选择与侧边对话历史一致；② 灰色用户气泡、左侧助手回复及阅读宽度一致；③ 白色底与青绿色主操作一致；④ 简短方案和固定输入框一致，实际方案更紧凑以适配720px高视窗；⑤ 手机折叠侧栏并保留账号入口。未展示参考图中的虚构时间戳。参考图是设计依据，用户尚未逐项验收视觉效果。

本机18876已更新，健康接口与新版页面通过检查；重启后需重新登录，原账号、设置和研究记录保留。恢复的实际对话可继续调整，但未自动执行真实研究。真实数据采集、补证与两期业务试读仍需后续验证。

### 2026-10-07：品牌任务三栏、节点检阅与本机自动执行

按 Mika 对长期任务入口、手动配置、节点流程和自动执行时间的要求实现：左侧按品牌分组列任务；中间显示实际研究节点、节点说明、手动设置和执行记录；右侧保留持续对话。支持搜索、折叠品牌、任务改名和跨品牌切换；每次修改复用同一任务并保留方案版本。手机使用“对话修改／查看任务”切换两个区域。

自动执行支持一次、每天、每周及明确的自然语言时间说明，例如“每周一早上9点，看上周的讨论”。手动保存与对话提议均先预览下次执行；点击启用后才生效，随时可暂停。时间、观察窗口和每次运行保存在任务下，确认、暂停与时间提议进入同一对话，刷新后恢复。

执行绑定启用时的方案、查询、来源与单轮额度，只滚动观察及比较窗口。修改方案或时间后暂停待重新确认；旧方案、未完成规划、账号或品牌权限失效、背景来源失败及未知调用结果均阻止后续自动执行。并发触发及重复确认不得重复调用；已有研究未结束时跳过该次。调度每30秒检查，仅服务运行时有效，关机、重启、明显休眠或错过的时刻不补跑；已发出的请求不能撤回。没有增加月度合同额度结算、操作系统常驻任务或商用SLA。

验证：`.venv-signal-desk/bin/python -m pytest -q tests/signal_desk` 为 **242 passed, 6 warnings**；原日报与频道36项分进程通过，共278项。6条均为既有feedparser弃用提示。编译、UI JavaScript语法、`git diff --check`通过。独立审查复核84项调度及工作区测试，20个并发触发只产生1个任务；排队后撤权阻止来源调用。

Codex in-app browser 在独立虚构服务18976验证节点点击、手动问题与关键词更新、对话改日期、任务改名、搜索及切换、时间提议、启用／暂停／重新启用、刷新及重启恢复、手机配置。推进虚构时钟后由实际30秒调度线程触发一次研究，采集使用10月1—7日窗口，结果停在待审阅，之后人工批准；失败路径暂停后续执行。时间设置不请求规划模型，也不立即采集。所有模型与来源均为隔离替代，未启用真实品牌的自动执行。

#### 视觉与交互对照

设计依据为本轮生成的[完整参考图](/Users/mikawang/.codex/visualizations/2026/10/07/01a11509-f964-71f2-9eb4-227a1e6d1b56/signal-desk-workbench-concept.png)，参考 [MiniMax Design 公开介绍](https://design.minimax.cn/) 的对话、节点画布与关键审核思路。实际图由in-app browser截图并用`view_image`与参考图在同一验收中查看： [桌面1536×1024](/Users/mikawang/.codex/visualizations/2026/10/07/01a11509-f964-71f2-9eb4-227a1e6d1b56/signal-desk-workbench-desktop.jpg)、[手机390×844流程](/Users/mikawang/.codex/visualizations/2026/10/07/01a11509-f964-71f2-9eb4-227a1e6d1b56/signal-desk-workbench-mobile.jpg)、[手机时间设置](/Users/mikawang/.codex/visualizations/2026/10/07/01a11509-f964-71f2-9eb4-227a1e6d1b56/signal-desk-workbench-mobile-time.jpg)。截图为虚构品牌验收数据。没有使用外部Playwright操作浏览器。

| 对照点 | 参考与实际证据 | 修正或有意差异 |
| --- | --- | --- |
| 三栏与容器 | 同为264px任务栏、中间节点详情及约398px对话栏；白色面板与细分隔线 | 保留顶部当前品牌选择，62px顶栏略高于参考，便于检查当前品牌 |
| 节点与图标 | 问题→实际来源→核对精选→人工审阅；补读为虚线支路，线条图标及选中问题的青绿色圆形图标一致 | 使用可点击DOM与按尺寸计算的SVG连线，不把参考图铺作页面；状态来自实际运行 |
| 节点间距 | 对照发现已执行节点新增状态后挤压首屏时间操作 | 收紧桌面运行状态图的垂直间距；最终1536×1024截图可同时看完节点、检阅区及时间操作 |
| 调色与字级 | 白色主面板、淡灰蓝任务栏、青绿色操作与选中态，标题与正文层级一致 | 复用现有品牌纯色按钮；不添加参考图的装饰头像；实际任务与方法文字可变 |
| 检阅与时间卡片 | 节点下有“手动修改”，时间卡片显示频率、时间、星期／日期和窗口 | 说明支持长文本与实际方法；增加“保存时间／暂停”供手动操作，状态和时间不使用虚构常量 |
| 对话及固定输入 | 右侧灰色用户气泡、助手回复、底部固定输入框与发送按钮一致 | 完整保留真实测试操作对话；时间确认与本机执行条件用实际服务文字，未复制参考图演示回复 |
| 手机 | 390px截图保留品牌与账号入口，流程图和两列时间字段可读 | 折叠任务栏，详情／对话切换；页面宽390px、图宽366px，无横向溢出，桌面无横向溢出 |

首屏文字对照：“新任务／研究流程／执行记录／手动修改／自动执行”等主要名称保留。新增品牌选择、任务分组标题、执行状态、“保存时间／暂停”和运行条件属于本轮实际功能；任务名、问题、消息及时间按实际记录显示。“启用”在暂停或已启用状态分别改为“重新启用／暂停”。没有新增开发协议、类型选择或技术诊断面板到用户主流程。结构、配色、字级、图标、节点连接与主要交互已按设计参考核对实现，无待修的内容遮挡或横向溢出；参考图尚未获得 Mika 的逐项视觉签核，不声明10/10或用户已接受设计。

本机18876沿用原启动脚本更新，健康检查与当前源码页面一致；原账号、品牌、研究及配置保留，重启后需重新登录。没有修改凭证、数据库schema或部署远端。临时虚构服务与数据验收后清理；保留上述截图及参考图用于检阅。真实供应商采集、正文补证与两期业务试读仍未由本轮虚构验收证明。

### 2026-10-07：Kestra 可管理工作流原型

Mika 同意先用本机原型验证“对话修改 → 实际流程 → 定时执行 → 持久人工检阅 → 模拟发布”。新增独立入口 **http://127.0.0.1:18977/**；18876 的账号、品牌、历史研究和来源配置没有迁移。原型只有澄野（虚构）这一品牌和一个研究任务，不能据此认定正式产品的多品牌工作流已经迁移完成。

原型复用三栏结构：品牌任务栏、实际节点与配置、持续对话。对话调用已配置的规划模型，能增加虚构竞品节点、修改研究问题、关键词、分析重点和模拟渠道。模块仅开放品牌样本、竞品样本、竞品对照、研究整理、人工检阅和模拟发布；不接受任意代码或外部 URL。尚未配置模型时明确显示演示模式，不将预设回复称为 AI 规划。

手动拖动位置只改布局；节点设置、连接或研究内容改变时产生新方案版本，暂停旧日程。支持新增连接、拖动端点重接、删除连接；环路、缺失依赖及绕过审核的图不能保存，界面恢复原方案。点击步骤直接定位到完整配置卡片。对话栏显示当前自动执行状态，避免将历史启用消息误认为当前状态。

#### 启动与停止

使用现有 `.venv-signal-desk` 与本机 Node，不安装全局依赖。初次启动前构建界面：

```bash
cd /Users/mikawang/Documents/GitHub/InsightBot-signal-desk/frontend/signal-desk-workflow-poc
npm --cache /private/tmp/signaldesk-poc-npm-cache ci
npm --cache /private/tmp/signaldesk-poc-npm-cache run build
cd /Users/mikawang/Documents/GitHub/InsightBot-signal-desk
bash scripts/signal-desk-workflow-poc.sh --model-config /Users/mikawang/Applications/SignalDesk-local/config.env
```

`--model-config` 仅读取既有文件中的 AI 连接设置，不修改该文件，不读取真实品牌资料。不传该参数时可通过环境提供相同 AI 配置；没有配置则进入明确标注的演示模式。前台原型服务用 Ctrl+C 停止；独立引擎由以下脚本管理：

```bash
.venv-signal-desk/bin/python scripts/signal-desk-kestra-runtime.py status
.venv-signal-desk/bin/python scripts/signal-desk-kestra-runtime.py stop
.venv-signal-desk/bin/python scripts/signal-desk-kestra-runtime.py start --timeout 55
```

运行时固定为 Kestra **1.3.42**、Temurin **21.0.12.1+1**，从官方发行源获取并验证校验值，解压在仓库忽略目录，不改系统 Java。本机尝试的 2.0.3 发行包要求 Java 25，且新增 controller 的监听隔离没有满足本轮要求，因此当前原型使用实际验证过的 1.3.42；正式接入前仍需单独验收升级路线。

界面 18977、Kestra API 18978、管理健康接口 18979 均只监听 `127.0.0.1`。引擎启用独立认证，匿名遥测与自动插件安装关闭，日志有限轮转；没有 Docker、生产服务或外部频道写入。运行时、H2、执行状态、独立认证与回调密钥均在忽略目录 `.cache/signal-desk-kestra-poc/`，不要提交或共享。此目录是续接与重启恢复依据；更换引擎版本时使用独立数据目录，不降级复用 H2。

#### 实际验证与边界

- 已有模型连接完成两次真实规划调用，输入仅有虚构品牌与样本方案：增加映山（虚构）竞品节点；修改竞品分析重点。返回的操作实际改变了公共方案、节点设置和连接。
- Kestra 原生 DAG 执行方案 v2 并停在 `PAUSED`。同时重启引擎和应用后，原执行、审核稿及已成功步骤的 task-run ID 保留。浏览器批准后执行成功，只有一次本机模拟发布记录，已完成步骤没有重跑。
- 原生 `ScheduleOnDates` 在北京时间 **19:20:01** 触发 v5，采用该版手动修改的关键词与重点，完成研究后等待人工检阅。选择“不发布”后结束，没有执行发布节点或新增发布记录。实际计时验收为一次；每天／每周已通过表单、编译与协议检查，长期重复调度尚未验收。
- 在真实浏览器新增品牌线索到研究判断的依赖，重接为竞品线索到研究判断，方案依次成为 v6／v7；原 v5 触发器被禁用。执行 v7 后读取引擎定义，研究判断的依赖确为竞品对照与竞品线索。循环连接报错并保留 v7；最后删除额外测试连线，恢复清晰路径为 v8，布局拖动与整理不再递增版本。
- 测试结束时三次研究均为终态，只有第一轮批准产生模拟发布。当前方案自动执行未开启，旧测试日程已禁用，服务保留用于体验。执行、模型或日程安装结果不明时不会自动重发，也不显示为成功。

验证：Signal Desk **296 passed, 6 warnings**，包含54项新增工作流、原型接口与运行时测试；原日报与频道36项分进程通过，本轮共 **332项**。6条为既有 feedparser 弃用提示。前端类型检查与构建、Python编译、启动脚本语法及 `git diff --check` 通过。构建保留 React Flow 的 `use client` 提示，此界面为本机 SPA。未验证真实供应商研究质量、专业编辑、真实频道发布、管理员模块管理、多品牌执行权限／预算、生产部署或商用 SLA。

Codex in-app browser 验收1536×1024桌面及390×844手机：节点拖动、配置、连线、重接、无效连接恢复、人工审核、时间模式、品牌任务栏、连续对话及刷新恢复。发现并修正图标类名与端点识别冲突造成的连线崩溃；最终版本重测通过，浏览器无新增脚本错误。节点完成状态无内容重叠；手机字体、点击后配置定位及尺寸变化适配已复核，页面无横向溢出。

实际截图：[桌面流程图](assets/signal-desk-kestra-canvas.jpg)、[重启后的待审阅结果](assets/signal-desk-kestra-review.jpg)、[实际定时执行结果](assets/signal-desk-kestra-scheduled-review.jpg)、[手机流程](assets/signal-desk-kestra-mobile.jpg)、[手机时间检阅](assets/signal-desk-kestra-mobile-time.jpg)、[手机对话](assets/signal-desk-kestra-mobile-chat.jpg)。手机每周时间截图为未提交的配置检阅状态，未留下未来自动任务。

### 2026-10-07：提交前完整回归

旧日报与大屏测试在导入时全局替换 `feedparser`、`requests`，会干扰同进程的 Signal Desk 测试。本轮移除这些全局替换，保留各测试已有的局部 mock；可以按 CI 的入口运行完整测试：

```bash
PYTHONPATH=.:editorial-intelligence .venv-signal-desk/bin/python -m pytest -q
```

本机 Python 3.14 下为 **626 passed, 6 warnings**，6 条仍为既有 feedparser 弃用提示。React 原型类型检查与构建、Python 编译和启动脚本语法检查通过。上述六张截图仅包含虚构品牌，已存入仓库供 PR 审阅；本机运行状态、模型配置、认证信息和供应商资料仍不进入 Git。本轮本机结果不替代 CI 的 Python 3.12 验证或真实品牌业务验收。

现有 PR CI 只安装主应用的 `requirements.txt`。依赖 LangGraph／SQLite checkpoint 的 9 个测试模块在缺少独立运行依赖时明确跳过；完整 Signal Desk 验证还需安装 `requirements-signal-desk.txt`。本机模拟缺少 LangGraph 的入口为 **390 passed, 9 skipped**，独立 Kestra 原型与主应用回归仍执行。本轮没有修改 CI 配置或将独立运行依赖并入主应用。

### 2026-10-07：PR #15 首轮审阅修复

首轮审阅发现一项 P1、四项 P2；均已复现并修复：

- 登录成功保留该客户端在十五分钟内的失败次数，防止用有效账号反复清除针对其他账号的限流。
- RSS 日期按 UTC 转换，主机时区不再影响发布时间；达到总条目上限即停止取后续源，零额度不发出请求。
- 同一来源的重复证据优先保留可用正文，并同步正文等级与限制说明；长标题不能覆盖短正文，顺序不影响结果。证据 ID、来源及各次快照保留，空正文不能提升等级。
- Kestra 启动响应不明或应用重启后，按冻结方案及请求标识只读查找执行。找到后恢复原执行；只有完整核对确认未创建时才解除启动阻塞，必须再次手动发起新请求。旧请求被保留为未启动状态，迟到回调不能执行任何模块。服务不可用、记录不完整、分页超出范围或请求对应多个执行时继续待核对，不自动重发启动。

新增 **36 项**回归，覆盖有效登录穿插失败尝试、三种主机时区、零额度／后续源故障、正文长度与顺序、启动丢响应、未创建、重启、迟到回调、并发确认及不完整引擎查询。完整入口为 **662 passed, 6 warnings**；6 条仍为既有 feedparser 弃用提示。Python 编译和 `git diff --check` 通过。

在保留的 Kestra **1.3.42** 上只读核验新查询：原执行正确匹配、虚构未发出请求确认为不存在；原执行仍为 `SUCCESS`。本轮恢复场景使用隔离单元测试，没有新建真实研究、调用供应商或模型、启用日程或发布结果。修改已纳入同一 PR 的审阅范围；合并与部署仍须另行决定。

### 2026-10-07：两页营销产品介绍

按 Mika 的追加要求，介绍内容改为 imagegen 制作的两页精简横版：第一页讲面向品牌与营销团队的 AI 研究工作台价值；第二页只保留三步使用方式及卖点、内容、竞品、人群四类问题。暂用 Signal Desk 作为展示名，保留内部试用标记；没有加入未经验证的客户、成效、数据覆盖或正式发布承诺。

交付：[第一页](intro/Signal-Desk-introduction-01.png)、[第二页](intro/Signal-Desk-introduction-02.png)、[两页 PDF](intro/Signal-Desk-product-introduction.pdf)。最终图片均为 1672×941；PDF 保持原图比例与两页顺序，已逐页渲染检查。生成与修订提示词保存在 [本机视觉记录](/Users/mikawang/.codex/visualizations/2026/10/07/01a11509-f964-71f2-9eb4-227a1e6d1b56/signal-desk-intro/two-page-prompts.json)。本轮是介绍材料，不改变 PDD 或产品能力验收状态。

### 2026-10-07：产品介绍可编辑 PPT

追加交付 [两页可编辑 PPT](intro/Signal-Desk-product-introduction-editable-YGGBi.pptx)，保留原图构图、纸张质感与绿色视觉。按 Mika 的修改删除第一页“问题导向／少量精选／证据可查”及第二页末尾的说明口号；采用 agency-writing 改写正文、使用步骤与场景文案。YGGBi 使用官网项目的正式绿色字标，原始 PNG 字节完整嵌入；出处见 [官网 Logo 规范](/Users/mikawang/Documents/GitHub/yggbi-com/docs/logo-usage.md)。原来的 PNG／PDF 保留作参考，更新内容以本次 PPT 为准。

主体标题、正文、步骤编号、场景标签、两个流程箭头及背景可编辑；纸张插画、小图标和字标为独立图片，插画内的报告标题保留在图片中。插画已通过 imagegen 分离为透明素材。更新预览：[第一页](intro/Signal-Desk-product-introduction-YGGBi-01.png)、[第二页](intro/Signal-Desk-product-introduction-YGGBi-02.png)。PPT 为 16:9，约 4 MB；27 处原生文字和 2 个原生连接箭头已核对，文件结构与重新导入检查通过。最终文件经 Artifact Tool 与配置了本机中文字体的 LibreOffice 逐页渲染检查。PowerPoint 已打开初版第一页核对显示，最终版的原生检查因电脑锁屏中断，没有完成实际编辑保存测试。重建脚本和验证记录保存在 [本机制作目录](/Users/mikawang/.codex/visualizations/2026/10/07/01a11509-f964-71f2-9eb4-227a1e6d1b56/signal-desk-intro/pptx-work/build/)。

### 2026-10-08：周报呈现演示

按 Mika 的要求制作预期周报样稿，以原型中的虚构品牌澄野及通勤杯议题展示两条本周发现、一条上期回看、一个讨论问题与范围说明。前三类内容用自然短段落呈现，第三页展开六段模拟体验及对应判断；全稿明确标为演示，不引用真实用户发言，也不作为实际采集或研究结果。使用 PDD 第7节的试点篇幅上限，沿用产品介绍的绿色视觉与正式 YGGBi 字标。

交付：[三页可编辑 PPT](weekly-demo/Signal-Desk-weekly-report-demo-YGGBi.pptx)、[三页 PDF](weekly-demo/Signal-Desk-weekly-report-demo-YGGBi.pdf)。预览：[本周发现](weekly-demo/Signal-Desk-weekly-report-demo-01.png)、[回看与讨论](weekly-demo/Signal-Desk-weekly-report-demo-02.png)、[依据展开](weekly-demo/Signal-Desk-weekly-report-demo-03.png)。主体文字、背景和依据表格均为原生可编辑对象，字标为独立图片。文件结构、篇幅、表格对象、字标原始字节和重新导入检查通过；保存后的最终 PPT 经 Artifact Tool 与 LibreOffice 逐页渲染检查，PDF 为该 PPT 的实际导出。未在 PowerPoint 中进行编辑保存测试。制作脚本与检查记录保存在 [本机制作目录](/Users/mikawang/.codex/visualizations/2026/10/07/01a11509-f964-71f2-9eb4-227a1e6d1b56/signal-desk-weekly-demo/build/)。本轮仅制作展示材料，不改变周报自动生成、真实研究质量或频道交付的验收状态。

### 2026-10-08：周报改为 HTML 邮件样稿

Mika 修正展示方向：周报应优先是一封精美的邮件，观点鲜明、文字简短，以适当的数据或图表支撑观点，末尾集中列出 References。已同步 PDD 第7.1节。之前的三页 PPT 保留作版式探索，本次展示以邮件样稿为准。

交付：[可编辑 HTML 邮件预览](weekly-demo/email/Signal-Desk-weekly-email.html)、[含 HTML 与内嵌图片的邮件文件](weekly-demo/email/Signal-Desk-weekly-email.eml)。样刊采用 lululemon 2026财年Q2的真实公开财报，以中国大陆净收入公布口径 +4%、剔除汇率 −2%、可比销售剔除汇率 −8% 支撑“营收增长不等于原有生意更强”的判断；显示季度截至日期与2026-09-03公告日期，不冒充当周新采集结果。两项 References 直接链接公司公告及 SEC 10-Q，图表与 CSV 保存于 `weekly-demo/email/assets/`，沿用正式 YGGBi 字标。

邮件采用单列、表格布局、内联 CSS 与手机样式，图片通过 MIME Content-ID 内嵌，附纯文本回退；预览 HTML 自包含。收件人与发件地址留空，邮件未发送。网页预览在1280、390与320像素宽度检查图片、横向溢出、品牌标识、引用锚点和控制台；修正窄屏字标换行与预览 favicon 404。浏览器为隔离的无头 Chrome，经现有 Playwright 调用；未使用用户登录会话。MIME 结构、图片对应关系和 logo 字节已核对，尚未做 Gmail／Outlook／Apple Mail 的实际收件测试。制作与预览检查记录位于 [本机制作目录](/Users/mikawang/.codex/visualizations/2026/10/07/01a11509-f964-71f2-9eb4-227a1e6d1b56/signal-desk-weekly-email/)。本轮未实现产品内邮件发送或定时投递。

### 2026-10-11：千瓜授权复核与真实链路发现

按续签请求复核千瓜授权。结论是**当前不需要续签**；同时发现两处会使真实研究无法产出证据的链路问题。以下均为只读验证：未调用规划或编辑模型，未修改凭证，未启用日程，未发布结果，未使用任何客户材料。

#### 授权状态（实测）

- 工作树 `/Users/mikawang/Documents/GitHub/qiangua-insights`，解释器使用本工作树 `.venv-signal-desk`。
- `auth test` → `{"status":"success","user":"Jessie Zhou"}`。
- `auth health-check` → `{"status":"ok","message":"授权正常","user":"Jessie Zhou","cookie_freshness":{"status":"fresh","days_old":2}}`。
- `auth.check_permissions` → `{"total":7,"available":7,"blocked":0}`。
- 凭证文件 `auth/qian_gua_cookie.json` 的 `updated_at` 为 `2026-10-08T19:59:45`，晚于本文件先前的 10-07／10-08 记录，此前未登记。故 10-07 的 401 属历史状态，已不适用。
- Signal Desk 侧直连复核：`SIGNAL_DESK_QIANGUA_REPO` 未设置，适配器按默认同级目录解析到 `qiangua-insights`，脚本存在、Python 环境正确，`QianguaAdapter().auth()` → `True`。授权门禁已通过。

#### 发现一：检索能力接线错误，真实运行必然零稿

- 适配器 `QianguaAdapter.search()` 调用 `content.search_notes`，底层为 `POST /v1/Note/GetNoteHotList`（通用笔记热榜，非关键词检索）。
- 实测返回 10 条：`XhsNoteUrl` 全为 `null`、`WebShare` 为空字符串，`normalized_items[].url` 全为 `None`。该能力自带限制说明亦写明 `Results are from the general note hot list, not keyword-specific samples.`
- `_note()` 要求 URL 合法才保留，故全部计入 `missing_url`，`kept=0`，证据池为空。
- 正确路径实测可用：`keyword.search` 取得 `WordId`（例：`潮玩` → `WordId 62271`），再以 `keyword.notes` 传 `word_id` + 日期窗，返回带 `Url`（例：`https://www.xiaohongshu.com/explore/6ac2158b0000000002012a71`）以及作者、发布时间、互动数据的笔记样本。
- 影响：按当前接线，任何真实研究都会得到零条可用来源；这与"证据不足"在结果上无法区分，也使 `missing_url` 长期偏高而不被识别为接线故障。

#### 发现二：正文不可得，证据强度上限为 title_only

- `content.search_notes` 返回中 `Content` 与 `VerifyContent` 均为空字符串；仅 `MatchContent` 非空，但它是带 `<font>` 高亮标记的关键词命中片段（约 160—200 字），不构成完整正文。
- `keyword.notes` 返回 URL 与指标，无正文字段。
- `note.search_by_url`（`POST /Track/SearchNoteByUrl`）返回 40 个字段全部为元数据，不含 `Content`／`Desc`／`NoteContent`。
- 本地 `qiangua-insights` 的 client 与 capability 清单中未见任何返回笔记正文的接口。
- 影响：`_note()` 的 `source_grade` 恒为 `title_only`，限制说明恒为"仅标题，未取得正文"。阶段 C 的正文补读在真实链路上无法把来源升级为 `qiangua_body`，而 PDD 第 4.2／7.4 节要求主张须由证据支持并说明个案边界——仅有标题时产品只能输出线索，无法交付其承诺的判断强度。

#### 边界与后续

- 本轮未执行真实品牌研究，未验证同议题两期业务试读、长期重复调度与商用可用性。
- 上述两处链路问题**尚未修改任何代码**；修法与范围（能力替换、正文来源、`delivery_profile` 是否相应收窄）需另行确认后再报验收。
- 千瓜为公开笔记样本。以上验证取自中性关键词，不涉及客户材料，未向外部模型发送数据。

### 2026-10-11：千瓜前端抓包复核——正文不可得已获 endpoint 级证据

针对"发现二"，本轮在 `qiangua-insights` 仓库做了实时驱动抓包复核（注入已存 Cookie + 无头 Chrome + Vuex 运行时内省，非离线 HAR 猜测），结论升级为 endpoint 级证据：

- 抓包脚本：`qiangua-insights/scripts/har_capture_notes.py`；产物写 `.cache/har/`（已 gitignore）；完整记录见该仓库 `docs/mcp/note-body-research-20261011.md`。
- 千瓜前端共暴露 **5 个可用的笔记级 endpoint**，其中 `v1/note/GetNoteDetail`（参数 `noteId` + `sign`，42 字段）和评论明细 `v5/note/GetNoteComments` 为本次实测打通；`GetNoteDetail` 此前未注册进上游仓库。
- 对同一篇真实笔记逐接口核对：`GetNoteDetail` 42 字段全为元数据；`GetNoteAnalyse` 60 字段中 `VerifyContent` 为空字符串；`GetNoteListByComment` 单条 item 的 `Content`／`VerifyContent`／`MatchContent` 均为空，仅 `ContentWordSegment`（词段+权重）有值。
- 全站 396 个前端 JS chunk 静态扫描，未见任何 `GetNoteContent`／`NoteBody` 类 endpoint 常量。
- **判定**：千瓜官方前端不提供笔记正文，`source_grade` 的 `qiangua_body` 等级在当前接口面下不可达。这不是适配器实现缺陷，而是产品契约问题——「正文补读」需重新定义为「评论命中片段 + 词段权重 + 标签 + 互动结构」的组合证据，或在 PDD 中下调「洞察」一词的准入门槛。
- 上游文档同步：`docs/mcp/note-body-research-20261011.md`（新建）、`har-capability-audit.md` 与 `endpoint-research.md`（加交叉指引）。
- 本轮**未改动任何 capability 代码**，也未改动 Signal Desk 代码；若要把 `GetNoteDetail` 注册为上游 capability，需按 `qiangua-insights/AGENTS.md` 第 141 条同时改三处并补 mock 测试。

### 2026-10-11：千瓜配额实测——额度最窄能力不能进关键路径

在确认正文不可得之后，进一步核验「长期稳定运行」所需的数据预算，实测拿到逐功能配额表（完整表见 `qiangua-insights/docs/mcp/quota-map-20261011.md`）：

- 查询入口：`GET User/GetUserOperationCountV3?type=<N>`。额度**按功能独立**，非账户级单一池。本周期 2026-09-22 10:30 → 2026-10-22 10:30（按购买日滚动，非自然月）。
- 宽额度：`热搜词搜索` 6000、`笔记分析`／`跳转原文` 4500、`笔记搜索` 4000、`达人搜索` 2400、`关键词搜索` 800（次/月）。
- 窄额度：`评论搜索` **15 次/月，本周期已用尽（剩余 0，已触发额度提示）**；`评论趋势分析` 15；`店铺搜索`／`店铺分析` 各 10；`笔记内容解析`／`达人内容解析` 各 20；各 `*对比` 50—200。
- 零额度：`直播录屏`、`素材搜索／分析`、`达人健康等级更新`、`评论相关笔记分析报告`。
- 计量性质：**前端流程层门控，非数据接口层**——直连 8 个数据 endpoint（笔记搜索、笔记分析、笔记详情、笔记评论、取 URL 等）实测消耗均为 0；扣减发生在前端调用 `GetUserOperationCountV3` 校验之后。**该路径绕开平台计费约定，不作为产品方案依据，仅作事实记录。**
- **对产品的影响**：以「每月 4 期、每品牌每期 1 次调用」换算，单账户可支撑品牌数分别为——笔记搜索 1000、笔记分析／跳转原文 1125、达人搜索 600，而 **评论搜索仅 3**、店铺搜索 2、笔记内容解析 5。即：任何依赖评论数据的「每期等量」交付承诺，在额度层面即不可实现，与正文不可得叠加后，评论数据在两个维度上都无法充当长期主要证据源。
- 反向结论：`source_grade` 的重定义应**优先落在宽额度能力上**（笔记分析 + 跳转原文 + 笔记搜索的组合证据），把评论数据降为「低频定向补证」，并要求调度器按剩余额度做采样预算与降级，而不是把窄额度能力写进关键路径。
- 本轮同样**未改动任何代码**。

### 2026-10-11（晚）：适配器切 v4 ＋ 证据等级对齐——本轮首次改代码

Mika 决策："设了上限。可以切 v4。" 前几轮结论均为"代码一行未动"，本轮起不再成立。

**改了三个文件**（详见 `JUSTONEAPI-ASSETS.md` §2.7）：

- `insightbot/signal_desk/providers.py`：`search-note/v2` → **v4**。**不是换 URL 那么简单**——v4 把参数名全改了（`sort`→`sortType`、`noteTime`→**`timeFilter`**、`noteType '_0'`→`'ALL'`），且返回结构由 `data.items[].note` 改为 **`data.notes[]`**（元素直接是 note，无 `model_type` 包裹）。只改路径会让**时间筛选静默失效**。
- 同文件：`source_grade` 由 `'search excerpt'` 改为 **`'search_snippet'`**。原值不在下游低等级词表 `('title_only','search_snippet','rss_snippet')` 内 → `_excerpt_rank` 兜底判为中等级，且 `editorial_v2` 的"仅有摘要不能支持完整判断"守卫**完全不触发**。这与方法论 §2.2 刚写下的"把截断摘要当正文引用是最容易犯的错"**是同一个错误，只是发生在代码里**。**一处改动，三处守卫自动恢复**（`core.py` / `editorial_v2.py` / `research_v2.py` 一行未动）。另补 `desc_length` 与 `body_verified: False` 两个可程序化检查的字段。
- `tests/signal_desk/test_workflow.py`：`test_verified_search_normalization` fixture 从 v2 结构改 v4 结构；**新增** `test_search_summary_is_graded_as_snippet` 把等级修复锁进测试。
- 新建 `scripts/check_v4_parser.py`：用 2026-10-11 保存的**真实 v4 响应**（3 页 57 条）离线校验，不联网不耗额度 → `parsed 57 notes; longest desc = 60 chars; grades = {'search_snippet'}`；`_excerpt_rank('search_snippet')=0` 而旧值 `'search excerpt'=1`（确证曾被误判）。

**账户状态变化**：令牌由 `Default` 换为 **`SignalDeskTest`**，`budgetAmount 10.9`／`usedAmount 0.9`／`remainingAmount 10`。⚠️ **该上限是令牌级而非账户级**——只约束绑定此令牌的通路，若 codex 侧仍用 `Default` 令牌则不受此上限保护，共享同一账户余额。

**测试环境说明（既有状态，非本次引入）**：`tests/signal_desk/` 在本机被 module 级 `pytest.importorskip("langgraph.checkpoint.sqlite")` 跳过（缺 `requirements-signal-desk.txt` 的隔离运行时），故改用真实响应做等价校验，强度不低于 mock 测试。

**未动**：`workspace.py`（`:137` 仍只取 `queries[0]`）、`web.py`、`core.py`、`editorial_v2.py`、`research_v2.py`；代码通路仍缺 `JUSTONEAPI_TOKEN`。**遗留**：`METHODOLOGY.md` §5.2 的八等级与代码现行词表**并存未打通**，正式切换需一次显式映射。

> ⚠️ **更正（同日深夜）**：上段"测试环境说明"**结论不成立**。实测 `.venv-signal-desk/bin/python` 依赖齐全（含 `langgraph`／`httpx`／`requests`），`tests/signal_desk/` **可以直接真实运行**。此前判断为"缺隔离运行时故被 skip"是误读，已改为**真实 pytest 全量运行**（本轮 351 passed）。`check_v4_parser.py` 保留为**零成本前置门禁**，但不再是唯一验证手段。

### 2026-10-11（深夜）：证据等级单一真源 ＋ 千瓜幻影等级定性 ＋ 费控中台

Mika 指令："映射也做了。保留（`total` 语义），下次再验证。导了一份价目表看是否有用……也许可以让我们的产品本身能够有个费控、额度中台？"

本轮一次做完三件事。

#### 一、证据等级收敛为单一真源（`grades.py`）

上一轮的修法（`'search excerpt'` → `'search_snippet'`）只是**让 `providers.py` 对齐代码现行词表**，并未消除"两套词表并存"。本轮从根因下手：新建 `insightbot/signal_desk/grades.py` 作为唯一承载。

- 八等级 + 两个标记值（`unverified`／`external_context`）+ `rank` + `summary_only` + kind 谓词 + legacy alias 表；`GRADE_VOCABULARY_VERSION = '2026-10-11.1'`。
- **未知等级改为 fail-closed** → 归 `unverified`（rank 0、`summary_only=True`）。**根因不再是"用错了词"，而是"词表可以分叉"；fail-closed 让分叉必然被拒。**
- 四个调用点全部接入：`core.py`（`_excerpt_rank`／`_sample_kind`／默认值）、`editorial_v2.py`（守卫改 `grades.summary_only`）、`providers.py`、`research_v2.py`（`_note()` 及三处字段更名）。
- `scripts/check_v4_parser.py` 移除 `ast` 提取 hack，改直接 import；输出升级为三组检查（分级词表／legacy token 解析／unknown fail-closed）。
- 新增测试：`test_legacy_grade_tokens_still_resolve`、`test_unknown_grade_fails_closed`；`test_search_summary_is_graded_as_segment_not_body` 等 5 项重命名对齐新词表。

**⚠️ 必须知晓的后果**：`qiangua_body` → `note_segment`（`summary_only=True`），而守卫现在对所有 `summary_only` 材料生效 → **千瓜单源证据被完全排除在客户可交付卡片之外**。这是"摘要 ≠ 正文"方法论的**正确**结果，但确实改变了产出面。三条出路见 `METHODOLOGY.md` §9.2 第 13 项（推荐：千瓜价值归位于结构层／趋势层，本就不受该守卫约束）。

#### 二、千瓜 `note.search_by_url` 实测：确认无正文

用千瓜 CLI 真实拉取，逐字段检查：**返回 40 个字段，无任何内容字段**（`Title` 17 字符、`Tag` 空、`VerifyContent` 不存在）。

→ `qiangua_body` 是**幻影等级**：代码里存在，但对应能力在任何接口上都不存在。**千瓜在本项目里最高只能到摘要级**；`note_body` 唯一来源是 JustOneAPI detail 接口（同条笔记：搜索 59 字符 vs detail 108 字符）。

> 执行细节：`.workbuddy` 的 Python 3.13.12 缺 `requests`，改用 `/Users/mikawang/.pyenv/shims/python3`（含 requests 2.33.1）才跑通千瓜 CLI。

#### 三、价目表 → 费控／额度中台

Mika 导出的价目表落盘为 `config/pricing/justoneapi-pricing-20261011.csv`（296 行，`¥` 已剥离、`允许/未开通` → `allowed/unavailable`），并建两层代码：

| 层 | 文件 | 内容 |
| --- | --- | --- |
| 报价 | `pricing.py` | `normalize_id()`／`Quote`（含 `chargeable`）／`price_table()`（带 key 冲突检测）／`quote()`／`price_of()`／`cheapest()`／`table_summary()`；`EXPORTED_AT` 记录导出时点 |
| 门禁 + 账本 | `costcontrol.py` | `Envelope`／`Decision`／`BudgetDenied`；`load_ledger`（畸形行 raise，不跳过）／`append_ledger`（`0o600`）／`reserved`／`remaining`／`estimate`／`quote_recipe`／`authorize`／`require`／`settle`／`reconcile`／`report` |

**关键设计**：① `chargeable = unit_price is not None and permission == PERMISSION_ALLOWED` —— **未知单价／未开通端点一律拒付**（fail-closed，不是"按 0 算"）；② **pre-call reserve** 先在账本写预留行，防重试／并行／双通路对同一余额重复授权（双花）；③ 端点命名归一，REST `/api/xiaohongshu/search-note/v4` 与 MCP `xiaohongshu.search_note_v4` 共用同一 join key `xiaohongshu_search_note_v4`。

**价目表关键读数**：296 端点 × 35 平台，¥0.05—¥1.50；不可定价 2 条（京东 `get-item-detail/v2`、pixabay `search-image/v1`，均 `未开通`）。小红书 16 端点中 15 个 ¥0.15、1 个 ¥0.20（`search-note/v4`）、1 个 ¥0.50（`ask-dots`）——**本项目主链路恰好全在最便宜档**。

**研究成果**：`scan` **¥0.20** ／ `probe` **¥0.85** ／ `frame` **¥1.50**（对应方法论 §4 三模式）。

**⚠️ 一处必须纠正的旧结论**：`get-note-detail/v1` 此前记为"未观测到扣费（≤¥0.10）"——**错**。官方价目表确证为 **¥0.15**（与 v2 同价），`get-note-comment/v2` 亦为 ¥0.15。误判根因是**计费异步结算**：5 次调用理论值 ¥0.90 − 实测 ¥0.75 = ¥0.15，恰好等于**一笔 detail 尚未入账**。**纪律：单价以官方价目表为准，余额只用于对账。**

**测试**：新建 `tests/signal_desk/test_costcontrol.py` 16 项；首轮 7 项失败（配方端点用模糊简称命中不了价目表；算术期望错）→ 修正后全通过。**全量 351 passed**。

**未动**：`workspace.py`、`web.py` 及真实调用路径——`costcontrol` 尚未强制接入 `require()`，因此**门禁目前是"可用但未强制"**。代码通路仍缺 `JUSTONEAPI_TOKEN`。**保留待验证**：v4 `total` 字段语义（Mika 裁定）。

---

### 2026-10-11（下午续）：层与实现核对 → 正文通路接通

**触发**：Mika 认可 L1—4+T 分层逻辑，要求核对代码实现是否符合。核对方式是**按调用链与引用计数逐层核实**，不凭印象。

**核对结论（详见 `METHODOLOGY.md` §2.5）**：

| 层 | 判定 |
| --- | --- |
| L1 内容层 | 🟡 部分（检索 + 正文；**评论未接**） |
| L2 人群层 | ❌ 零实现，且**等级体系里没有位置** |
| L3 结构层 | ❌ 零实现（`brand_structure` 等级 0 处引用） |
| L4 商业层 | ❌ 零实现，**等级体系里没有位置** |
| T 时间轴 | ❌ 零实现（`trend_series` 0 处引用） |

**四个最硬的发现**：

1. **`providers.py` 没接进 v2 主链路**：`collect()` 硬编码 `sources: ['qiangua']`，适配器默认 `QianguaAdapter()`；`providers.py` 只被 `workspace.py:137`（v1 遗留，只取 `queries[0]`）与 `__main__.py`（CLI）引用。而 `note_body` 的唯一来源恰是 JustOneAPI → **死结**：v2 唯一数据源最高只到 `note_segment`，守卫正确拒掉全部摘要级材料，**管线因此产不出任何卡片**。
2. **八等级是"文本粒度"词汇表，层是"决策层"词汇表**，两者不同维度。仅 L1 四个子层一一对应；`brand_structure`↔L3、`trend_series`↔T；**L2 与 L4 无等级**。
3. **三种模式只活在费控层**：`RECIPE_CALLS` 有 scan／probe／frame，而 `research_v2.py` 里一个都没有，执行层是单套 `BUDGET_DEFAULTS`。
4. **任务是 6 类不是 7 类**：代码与 PDD 均为六类模板，而 METHODOLOGY §3.5 已把"达人方向"升格为独立任务 → **文档先行、代码未跟**。

**执行（Mika 批准 A+B）**：

- **A. 正文通路接通** —— 新增 `providers.JustOneApiAdapter`（与 `QianguaAdapter` 同接口），接入 `research_v2.enrich()`；检索仍走千瓜。四个决定：无 token 退回千瓜片段（**行为逐字节一致，无回归风险**）；读取器进缓存键 `enrich-detail-<reader>-<hash>`；`BODY_OPERATIONS` 让 `body_reads` **跨读取器合并计数**；**形状不符直接报错，绝不猜测**。
- **实测 detail 响应形状**（一次真实调用，¥0.15）：`data` 是 **list**，正文在 `data[0].note_list[0]`（61 字段）——与 `search-note` 的 `data.notes[]` **形状不同**。响应约 **80k 字符**（`images_list` 占约 20k），而正文 `desc` 仅 108 字符**且全是话题标签** → **"取到 desc" ≠ "desc 有可引用内容"**。成本含义：正文是"重载荷、小文本产出"，再次支持"只对终选取"。
- **顺带修掉一处静默风险**：`justone_note_detail()` 原先只从环境读 token，而适配器的 `token` 参数形同虚设——两者不一致时会在很久之后以一句无关的"未配置"报错。现由 `_auth_token()` 统一解析。
- **B. 层需求变成可检查的声明** —— `LAYERS` / `LAYER_PRIMARY|AUX`；`METHODS[*].layers`（按 §3.8）；`IMPLEMENTED_LAYERS` + `layer_gaps()`。**缺口自动写进计划与运行结果的 limitations**（UI 渲染 `collection.limitations`，因此缺口对操作者直接可见）。

**新增测试**：`test_body_reader.py`（7 项）、`test_layers.py`（8 项）、`test_enrichment_v2.py` +5 项。**全量 375 passed + 1 既有失败**（kestra，与 HEAD 一致、与本轮无关）。

**其他**：`.gitignore` 新增 `docs/signal-desk/intro/`、`docs/signal-desk/weekly-demo/`、`.workbuddy/` 三条（二进制产物与 Agent 工作区状态不入库）；`PDD.md` 单独提交。

**未动 / 待决**：三种模式仍未上提到执行层；「达人方向」是否补为第 7 类，待 Mika 定契约口径。

---

## 2026-10-11 深夜（续）：把付费读取真正接到门禁上

Mika：「接着做」——即上一轮列的待决第 1 项（正文读者的费控接线）。

**问题不是"缺一个检查"，而是"门禁建好了却不在路上"**：`costcontrol.require()` 全项目**零调用**，付费正文读取实际只靠"是否配了 `JUSTONEAPI_TOKEN`"授权。**唯一付费调用点**是 `research_v2.enrich` 的正文补读，本轮把它逐次接上：

| 环节 | 行为 |
| --- | --- |
| 选读取器 | 有 token **且**声明了信封 → `JustOneApiAdapter`（**默认构造，生产路径与测试同一条**）；缺任一项 → 免费片段读取器 |
| 调用前 | `require({DETAIL_V1: 1}, 品牌 × 期信封)` → 先写 `reserve` 行（`channel='rest'`） |
| 调用后 | `settle(reservation_id, code=<业务码>)` → `code=0` 计费，其余按 ¥0 结算 |
| 缓存命中 | **不预留、不结算**（缓存命中不是调用） |
| 额度不足 | 本轮停止，后续目标标 `budget_denied`，写入 `collection.errors` |

**信封只从环境变量来**（`SIGNAL_DESK_SPEND_LIMIT_CNY`，可选 `SIGNAL_DESK_SPEND_LEDGER`）——**未声明即不花钱**，退回免费片段并把原因写进 `collection.limitations`（UI 可见），**不报错**。理由：默认值会让任何调用方在忘传参数时拿到花钱许可，而忘传参数恰恰最常见。**"有 token" 与 "被允许花钱" 必须分开。**

**接线暴露的三处只在真接线时才显形的问题**：

1. **结算不释放预留** —— `remaining` 原先只减 `reserve` 行 → 一次失败调用**永久占住**额度，一个月的失败足以把信封耗空而实际零支出（**一个会自己关闭的门禁**）。新增 `consumed()` ＝ 已结算实际值 ＋ 未结算预留估算值；`remaining` 改用它。**不变量保持**：未结算的预留照旧占用（防双花不减弱）。`reconcile()` 保留 `reserved()` 与账单对照——两个函数回答不同问题，不合并。
2. **业务码藏在错误文案里** —— `settle(code=...)` 拿不到码就只能按预留额多记失败调用。新增 `providers.ProviderError`（携带 `code`／`http_status`，且**不得携带 token**）。靠解析文案取码"能用，直到文案被改写"。
3. **参数名撞车** —— `enrich` 内既有的 `ledger` 是**源账本列表**，花费账本若同名会被直接覆盖，首轮实现即踩中（`TypeError: ... not 'list'`）。参数定名 **`spend_ledger`**。

**新增测试**：`test_spend_gate.py`（9 项，**打的是真门禁而非替身**）：预留→按码结算、失败按 ¥0 结算并退还、缓存命中不记账、额度不足不调用来源、未定价端点拒付、有 token 无信封不花钱、默认读取器就是真的那个、信封按品牌而非按运行、两个运行共用一个信封。`test_costcontrol.py` 16→**26 项**（新增信封来源／期界／账本位置）。

**全量 389 passed + 1 既有失败**（kestra，与 HEAD 一致、与本轮无关）。

**仍在外面的路**：MCP 侧（本机直调 `call_endpoint`）不走本账本，只能靠"同一个信封"的人工约定。**门禁保护的是管线，不是账户。**

**待决（新）**：信封是否按自然月重置（现由 `period_of()` 用 `Asia/Shanghai` 日界算期，但重置口径未定）。

---

## 2026-10-11 深夜（续二）：三模式上提执行层 + 达人方向补为第 7 类

Mika：「两项按顺序做」——即上一轮列出的待决第 12 项（三模式上提到执行层）与第 13 项（「达人方向」补为第 7 类）。按顺序执行，先 12 后 13。

### 一、三模式上提执行层（原问题：配方只能被报价，不能被遵守）

**问题的准确形状**：`costcontrol.RECIPE_CALLS` 有模式的调用量，`quote_recipe()` 能报出"一次 Scan 最多 ¥0.20"，但**执行层没有模式概念**——所有计划共用一套 `BUDGET_DEFAULTS`。于是**报价与执行之间没有连接**：一根打算读 12 条正文的探针，可以被报成 ¥0.55 的 Scan。

**落地方式（三件事）**

| 事 | 做法 |
| --- | --- |
| 额度由配方**派生** | `research_v2.mode_budget()` 从 `costcontrol.RECIPE_ALLOWANCES` 取 `queries`／`body_reads`；其余额度保持 `BUDGET_DEFAULTS`（§4 只说调用量与证据层，**没有出处就不另设数字**） |
| 默认模式 = `probe`，**派生额度恰好等于 `BUDGET_DEFAULTS`** | "不点名模式就不改变行为"的机械保证，也是**模式上线不带回归风险**的原因（测试锁定） |
| 计划**冻结**额度，执行**不重算** | 执行层读冻结的额度、不读 `mode` 标签——否则某天改了 `MODES`，一份批准过的 Scan 会**自己长大**成 Probe |

计划新增 `mode`／`mode_definition`／`mode_layers`；UI 计划摘要加一行「研究规模」；`previousPlan()` 的白名单补 `mode`（**否则一次对话修订会把模式静默重置回默认值**）。

### 二、照配方核对，发现 Scan 配方少报两次调用（本轮最值钱的部分）

| 发现 | 依据 | 处置 |
| --- | --- | --- |
| **Scan 只配 1 次检索** | §3 要求每个计划**至少一条挑战查询**（＋一条定向查询）→ 单查询的 Scan **连计划都过不了**（`planning_errors`） | 检索 **×2** |
| **Scan 不取正文** | §4 说 Scan 产出"**在用的词**"，§2.2 明令 ≤60 字符摘要**不可用于语言复用** → 只检索的 Scan **产不出它声称的产出** | 正文 **×1** |

→ `scan` 由 **¥0.20 改为 ¥0.55**；`probe`（¥0.85）／`frame`（¥1.50）**核对后无需改动**。

> **方法含义**：配方（成本）与产出（承诺）此前**从未互相核对过**。偏差只出现在**最便宜的那一档**——最便宜的一档最容易被当成"不需要成本"而免于核对。

### 三、发现并修掉一处"零额度可以被意外到达"的路径

额度最初在**调用时**按端点常量查配方。把 `DETAIL_V1` 指向配方里没有的版本号，`body_reads` 就会**静默变成 0**——而这看起来完全像"有意不买正文"。**零额度是一种政策声明，不能有意外到达它的路径。** 改为 `RECIPE_ALLOWANCES`（**导入时解析一次**），并由测试锁死（这个缺陷是测试先发现的，不是审阅发现的）。

### 四、两种缺口分开说

| 判据 | 含义 | 措辞 | 处置 |
| --- | --- | --- | --- |
| `missing_primary_layers(task)` | **管线**没有该层的读取器 | `未接入` | 补读取器 |
| `mode_shortfall(mode, task)` | **这一模式**不采集该层 | `未覆盖` | 换更大的模式 |

两者都写进计划与运行结果的 limitations。**不阻断**：用速读回答品牌竞争问题是**故意要一个更弱的读数**，但"更弱"必须写在纸上；是否改为阻断留待裁定（§9.2 第 15 项）。

### 五、花费按模式可分账

信封是「品牌 × 期」，同一期内三种模式**共用一个上限**；每笔预留现带 `mode`，`report()` 增加 `by_mode`／`spent_by_mode` 并可按模式过滤金额（**上限不被模式切分，只有花费按模式分离**）。没有这个标记，"Frame 真实成本是不是 ¥1.50"在账本上**无法被回答**。

### 六、「达人方向」补为第 7 类（第 13 项）

按 §3.5／§3.8 在代码 `METHODS` 中加入 `creator`（**主层 L2**，L1／L3 为辅），别名（达人／达人观察／creator／kol）、决策问题文案、规划提示词枚举、任务类型错误文案同步；**PDD §3／§4.3／验收清单的"六类"改为七类**（PDD §4.1 的表本来就是 7 行——**是 PDD 内部一直不一致**，这次一并收齐）。

**诚实代价**：L2 **零实现**，因此每一份达人方向计划都会带着 `未接入 L2` 的限制出行。这是把文档口径对齐代码的**必然结果**，不是新增缺陷。

### 测试与文档

**新增** `tests/signal_desk/test_modes.py`（11 项）、`test_spend_gate.py` +1（付费读取带 `mode` 且可按模式分账）；更新 `test_costcontrol.py`（配方金额与 `by_mode`）、`test_layers.py`（缺口集合加入 creator）、`test_research_v2.py`（参数化加第 7 类）。

**全量 402 passed + 1 既有失败**（kestra，与 HEAD 一致、与本轮无关）。

文档：`METHODOLOGY.md` → **v0.2.6**（**新增 §4.1**；更新 §2.5、§3.5、§3.8、§6.3、§6.6／§6.6.1、§8 表⑤、§8.2 B、§9.1 第 2 项、§9.2 关闭 12／13 ＋ **新增 15**、文末声明）；`JUSTONEAPI-ASSETS.md` → **v7**（新增 §2.8 F）；`PDD.md`（六类 → 七类，§3 补研究规模一句）；`DATA-SOURCES-v0.1.md`（Scan 调用量口径标记失效）。

**待决（新增）**：§9.2 第 15 项——模式与任务不匹配时是**提示还是阻断**；是否给每类任务配**默认模式建议**；当任务主层**两头都缺**（如 `audience` ＋ `scan`）时是否要求确认。

---

## 2026-10-12：**"7 failed"查清——根因是 WorkBuddy 注入的 shim，不是测试、不是临时目录**

**触发**：另一个评审 agent 报告"复用旧 `.pytest-tmp` 会让 7 个调度/工作区测试假性失败，`rm -rf .pytest-tmp` 后恢复"，并把根因初判为"顺序依赖/测试污染"。

**查证过程（每个假设都被反例打掉过）**

| 尝试 | 结果 |
| --- | --- |
| 复用同一 `.pytest-tmp` 连跑两遍全量 | **402+1、402+1** → "复用旧目录"不成立 |
| 两个 pytest 进程并发共用同一 basetemp | 确有干扰（1F+1E / 2F），但失败集与"7 个"不符 → 不是评审所见的现象 |
| `--basetemp=".pytest-tmp/run-$$"`（全新目录） | **恰好 7 failed**（scheduling ×5 ＋ workspace ×2）→ 与目录新旧无关 |
| 摘掉 `PYTHONPATH`（WorkBuddy 注入的 shim）后全量 | **403 passed, 0 failed**，系统默认临时目录直接可用 |

**真根因**：WorkBuddy CLI 向 shell 注入 `sitecustomize.py`（`/Applications/WorkBuddy.app/.../cli/vendor/shim`），其 broker 拦截 `Path.mkdir`。应用侧的合法幂等调用 `marker.parent.mkdir(exist_ok=True, mode=0o700)`（`workspace_v2.py`，调度标记与品牌目录各一处）在对**已存在路径**第二次 mkdir 时，broker 回 `EEXIST`，shim 抛 `PermissionError`——**没有按标准库语义吞掉 FileExistsError**。受害面：`test_scheduling_v2` ×5 ＋ `test_workspace_v2` ×2 **间歇性失败**（同一代码几分钟内先 402+1 后 7 failed，随 broker 是否应答波动，失败集随之漂移）。

**两个连带更正**

1. **kestra `test_stop_never_signals_pid_reused_by_another_service` 的"既有失败"重归类**：shim 下稳定失败，摘掉 shim **即通过** → 它是**环境噪声**，不是 `9fd9ab9` 的代码缺陷。此前"与 HEAD 一致、只依赖 stdlib"的判断方向对了一半——确实与信号台改动无关，但也不是代码问题。
2. **`--basetemp` 纪律作废**：它原本就是为绕开 shim（历史"169 个 setup error"同一根因）才存在的。摘掉 shim 后系统默认临时目录可用。**真基线：`env -u PYTHONPATH … pytest tests/signal_desk -q` → 403 passed, 0 failed。**

**标准测试命令（新）**

```
env -u PYTHONPATH .venv-signal-desk/bin/python -m pytest tests/signal_desk -q -p no:cacheprovider
```

**教训**：环境基线（"402+1 既有失败"）本身可能是被污染的——**当"既有失败"与某个注入层共存时，先怀疑注入层，再怀疑代码**。排除法顺序应当是：先摘注入（`env -u PYTHONPATH`），再谈顺序依赖。
