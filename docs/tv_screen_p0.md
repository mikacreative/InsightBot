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

`tasks.json` 任务级配置(见 `config/examples/tasks.example.json`):

```json
"screen": {
  "enabled": true,
  "refresh_seconds": 300,
  "rotate_seconds": 15,
  "theme": "auto"
}
```

- `refresh_seconds`:页面自动重载间隔(拉取最新生成内容),默认 300。
- `rotate_seconds`:板块轮播间隔,默认 15。
- `theme`:`auto`(默认,按电视本地时间 7:00-19:00 亮色、其余时间暗色)、`dark`、`light`。
- `image_rotate_seconds`:右侧图片轮播间隔,默认 10。
- 布局:左侧 36vw 竖屏报纸(刊头+板块轮播),右侧全出血图片区(轮播+时钟)。图片放在生成目录的 `img/` 子目录(`scripts/static/screen/img/`,jpg/png/webp 按文件名排序轮播),渲染时自动扫描;目录为空则显示品牌兜底块。
- 视觉风格:YGGBi 官网编辑风(深绿 `#0b4022` / 奶白 `#f2ecd4` 双色、报纸版式、emoji 在渲染层剥除)。
- 生成目录默认 `scripts/static/screen/`,可用环境变量 `SCREEN_OUTPUT_DIR` 覆盖。

## URL 与静态服务

`.streamlit/config.toml` 已开启 `server.enableStaticServing`,`scripts/static/**` 挂载在 `/app/static/**`(Streamlit 1.56 的固定端点前缀):

- 直连:`http://<host>:8501/app/static/screen/<task_id>.html`
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
