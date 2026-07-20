# 电视大屏 Dashboard P0

> Status: Implemented (P0)
> Date: 2026-07-17
> 方向来源: 《前台电视大屏 Dashboard(动态看板电视版)需求说明》(repo 外文档);Signal Desk 产品方向的展示端切片。

## 范围

P0 只做一件事:把一个任务(Daily_brief 行业雷达)的简报产出渲染成单页电视大屏,出一个 URL,在电视上跑通无人值守播放。

刻意不做(留给 P1/P2):多页/多模块配置化、欢迎屏·天气·时钟模块、多数据源、内网部署与开机自启运维手册、数据脱敏、gateway 公网暴露。

## 数据流

```
定时任务跑完 → final_markdown(## 板块 / ### [标题](url) / > 💡 *摘要*)
  → insightbot/screen.py 解析为板块/条目模型
  → 渲染自包含 HTML(深色 16:9、大字号、板块轮播、<meta refresh> 自动刷新)
  → 原子写入 scripts/static/screen/<task_id>.html
  → Streamlit 静态服务(/static/**)出 URL
```

- 生成挂在 `task_runner.run_task` 渠道分发之后,仅当非 dry_run、pipeline 成功且任务配置 `screen.enabled` 时触发;渲染失败只记日志,不影响投递与运行结果。
- 兜底:生成失败时旧 HTML 文件保留;电视端拉取失败时浏览器继续显示上次已加载页面。

## 配置

`tasks.json` 任务级配置(见 `config/examples/tasks.example.json`);**推荐在控制台「任务管理 → 📺 大屏」里开关和调整**,不要手改 JSON(改坏会导致加载失败——已有容错:控制台显示错误横幅、调度器保留旧状态,修复后自动恢复):

```json
"screen": {
  "enabled": true,
  "refresh_seconds": 300,
  "rotate_seconds": 15,
  "theme": "auto",
  "image_rotate_seconds": 10,
  "title": "可选,每任务刊头标题,覆盖全局 report_title"
}
```

- `refresh_seconds`:页面自动重载间隔(拉取最新生成内容),默认 300。
- `rotate_seconds`:板块轮播间隔,默认 15。
- `theme`:`auto`(默认,按电视本地时间 7:00-19:00 亮色、其余时间暗色)、`dark`、`light`。
- `image_rotate_seconds`:右侧图片轮播间隔,默认 10。
- 布局:左侧 36vw 竖屏报纸(刊头+板块轮播),右侧全出血图片区(轮播+时钟)。图片放在生成目录的 `img/` 子目录(`scripts/static/screen/img/`,jpg/png/webp 按文件名排序轮播),渲染时自动扫描;目录为空则显示品牌兜底块。
- 视觉风格:YGGBi 官网编辑风(深绿 `#0b4022` / 奶白 `#f2ecd4` 双色、报纸版式、emoji 在渲染层剥除)。
- 生成目录默认 `scripts/static/screen/`,可用环境变量 `SCREEN_OUTPUT_DIR` 覆盖。

## 新闻配图(P1)

任务跑完生成大屏页时,右屏图片可来自新闻本身:

1. **图源提取**:候选构建时从 RSS entry 提取 `media:content`/thumbnail/图片 enclosure/摘要首个 `<img>`,写入 `candidate.image_url`(`editorial_pipeline._extract_entry_image`),经 Stage 3 候选字典、Stage 4 `selected_items` 由代码带出(AI 始终不经手)。
2. **og:image 兜底**:终选条目无 feed 图时,抓文章页 `og:image` 补齐(并发、超时、失败静默)。
3. **服务端缓存**:所有图下载到 `img/news/`(URL 哈希命名),微信图片自动带 `mp.weixin.qq.com` Referer 绕防盗链;过滤非图片响应、<8KB 小文件和 <400×240 的图标图;每次刷新清理不再引用的旧图。实现:`insightbot/screen_images.py`。
4. **板块联动呈现**:右屏图片跟随左侧板块切换——当前板块有条目图就轮它的图,没有则回退 `img/` 通用占位图。

数据流:`run_task` hook 从 `stage_results` 提取 url→image 映射(`collect_selected_image_map`)→ `prepare_section_images` 解析+下载 → 渲染时注入 `SECTION_IMAGES` JSON。下载在任务线程内并发执行(≤终选条数张),全部失败也不影响运行结果。

注意:`python -m insightbot.screen` 从历史记录重生成时没有 image_map,只渲染通用占位图;classic 管线不带图。

## URL 与静态服务

`.streamlit/config.toml` 已开启 `server.enableStaticServing`,`scripts/static/**` 挂载在 `/app/static/**`(Streamlit 1.56 的固定端点前缀):

- 直连:`http://<host>:8501/app/static/screen/<task_id>.html`
- 索引页:`/app/static/screen/index.html` 自动列出所有开屏任务的页面(每次生成任一屏时同步刷新),多任务时电视各开各的 URL
- **依赖 Streamlit >= 1.56**:1.55 及更早版本的静态处理器按扩展名白名单服务,`.html` 一律返回 `text/plain`(浏览器显示源码);1.56 起改为 mimetypes 判断。requirements.txt 已锁定
- gateway 前缀暴露(如 `https://<host>/insightbot/app/static/screen/...`)属部署事项,按现有部署 runbook 执行并需 Mika 批准;敏感内容走内网,不公网暴露。

页面完全自包含(内联 CSS/JS,无外部依赖),电视自带浏览器、电视盒子或旧电脑全屏打开即可;开机自启与 kiosk 模式在播放端设置,不属于本 repo。

## 手动生成(免 AI 调用)

从最近一次含 `final_markdown` 的运行记录重新生成页面:

```bash
python -m insightbot.screen Daily_brief
```

## 相关代码

- `insightbot/screen.py`:解析、渲染、写入、CLI。
- `insightbot/task_runner.py`:screen hook(真实运行成功后触发)。
- `insightbot/config.py`:`load_tasks_config` 注入 `_task_screen`。
- `insightbot/paths.py`:`screen_output_dir()`。
- `tests/test_screen.py`:格式契约与 hook 行为测试。
