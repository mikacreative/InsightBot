# Signal Desk 测试环境与 env 准备

适用：2026-09-29 本轮 Alpha。产品设计见 [PDD](PDD.md)。本页的运行验证记录在末尾，设计目标不等于已经通过 live 验收。

## 运行位置

- 本地独立工作树：`/Users/mikawang/Documents/GitHub/InsightBot-signal-desk`；分支 `codex/signal-desk`。
- Mac mini：SSH alias `macmini`，`mika-macmini.local`。
- 测试根目录：`/Users/mikawang/Applications/SignalDesk-test`。
- 代码：`releases/20260929`；独立 Python 3.12：`venv`；运行数据：`state`。
- 服务仅绑定 `127.0.0.1:18876`。不接入原日报的 scheduler、channels 或生产配置。

在开发机建立隧道，然后打开 http://127.0.0.1:18876 ：

```bash
ssh -N -L 18876:127.0.0.1:18876 macmini
```

Mac mini 本机直接打开同一地址。经隧道访问者具有完整内部测试权限；当前没有商用账户体系，不开放公网。

## 需要准备的账号与变量

| 变量 | 是否需要 | 怎么准备 |
| --- | --- | --- |
| `SIGNAL_DESK_AI_BASE_URL` | Live AI 必需 | 支持 OpenAI Chat Completions 的服务根路径；按供应商要求包含 `/v1`，不填到 `/chat/completions`。|
| `SIGNAL_DESK_AI_API_KEY` | Live AI 必需 | 在所选 AI 服务后台创建测试专用 key，设消费限额。ChatGPT 网页订阅不自动等于 API 凭证。|
| `SIGNAL_DESK_AI_MODEL` | Live AI 必需 | 填该账号实际可调用的模型 ID；需要支持中文与 JSON 指令输出。须实测兼容性。|
| `JUSTONEAPI_TOKEN` | 实时社交采集必需；导入/回放不需要 | 在 JustOneAPI 后台准备 token，并确认小红书笔记搜索与详情权限、账户余额和 token 消费限额。Codex 的 MCP 登录配置不会自动传给 Mac mini。|
| `SIGNAL_DESK_STATE_DIR` | 建议显式配置 | Mac mini 使用 `/Users/mikawang/Applications/SignalDesk-test/state`，与旧系统数据隔离。|
| `SIGNAL_DESK_INPUT_FILE` | Sun Life 回放可选 | 指向测试机私有样本 JSON；不提交 Git。|
| `LANGGRAPH_STRICT_MSGPACK` | 建议保留 | `true`，只使用本流程的基础数据结构保存状态。|

AI provider 可先选公司已有、能稳定访问并支持 Chat Completions 的服务。首版只需一个 provider；不需要先配置多个模型、LangSmith、向量库、Redis、Pi 或其他 agent 平台。SQLite 保存本轮暂停与恢复状态。

JustOneAPI 官方接口使用 query `token`；代码不应记录完整请求 URL。参考[搜索 V2](https://docs.justoneapi.com/zh/api/xiaohongshu-rednote/note-search-v2)与[详情 V1](https://docs.justoneapi.com/zh/api/xiaohongshu-rednote/note-details-v1)。V2 的时间筛选不精确，导出中必须保留覆盖限制。

千瓜现阶段使用已授权的 CLI/MCP 采集后导入证据。本轮没有 Mac mini 上的自动千瓜适配器，也没有 `QIANGUA_API_KEY` 这个虚构配置项。后续接入时需在运行端单独验证千瓜直接接口授权，不把浏览器已登录当作 API 已授权，也不把本机 Cookie 自动复制到测试机。

## 配置方式

仓库的 `.env.signal-desk.example` 只有变量名和示例，没有密钥。应用本身不自动加载 `.env`；启动脚本加载测试目录下的 `config.env`。

在 Mac mini 上操作：

```bash
cd ~/Applications/SignalDesk-test
umask 077
cp releases/20260929/.env.signal-desk.example config.env
chmod 600 config.env
nano config.env
```

仅首次创建时运行 `cp`，已有配置不要覆盖。把路径和实际 provider 值填入 `config.env`；值包含空格时用单引号包裹，不在聊天中粘贴密钥。该文件是 shell 环境文件，只写自己信任的赋值语句。

模板中的 AI base URL 是格式示例，不代表已选定供应商。可以先留空 key/model 体验 Demo 和 Replay；选择 Live 不会自动退回演示结果。

## 三种运行模式

- **Demo**：预设流程演示，验证界面和状态，不是研究发现。
- **Replay**：历史真实证据＋预写的人工编辑卡片，验证审稿与呈现，不调用 AI、不重新采集。
- **Live**：使用所配置 AI 对输入证据编辑。实时采集需先显式调用已接入数据适配器；不能因模式叫 Live 就声称输入是实时或全量数据。

Sun Life 回放有 20 条千瓜列表样本，其中 2 条由 JustOneAPI 补读正文；独立样本仍是 20 条。界面加载样本后选 Replay，开始运行，检查来源和反例，填写审稿人，再批准或否决。批准只生成本地测试稿，绝不向客户或消息频道自动发送。否决是本轮终态，需要修改时新建运行。

## 启停测试服务

在 Mac mini 执行 `bash ~/Applications/SignalDesk-test/releases/20260929/scripts/signal-desk-test.sh start`；把 `start` 换成 `status` 或 `stop` 可检查或停止。修改 env 后先 stop 再 start。启动脚本不修改 launchd，机器重启后需要手动 start。日志在 `~/Applications/SignalDesk-test/server.log`，请勿开启包含请求 URL 或 headers 的 HTTP debug 日志。

## 本地开发

```bash
python3 -m venv .venv-signal-desk
.venv-signal-desk/bin/python -m pip install -r requirements-signal-desk.txt
.venv-signal-desk/bin/python -m insightbot.signal_desk --state-dir /tmp/signal-desk-dev serve --port 18876
```

`run --input FILE --mode replay --id RUN_ID` 启动；`status RUN_ID` 查询；`review RUN_ID --decision approve --reviewer NAME` 恢复。`--state-dir` 放在子命令之前。同一运行 ID 不可覆盖重跑，审核从持久化暂停点恢复。

## 凭证配置后的首次 Live 试跑

在测试机代码目录，先加载环境，然后单页采集、AI 编辑。每个输出文件与运行 ID 必须唯一，避免无意重跑付费请求：

```bash
cd ~/Applications/SignalDesk-test/releases/20260929
set -a
. ../../config.env
set +a
../../venv/bin/python -m insightbot.signal_desk collect --keyword '退休 照顾父母' --brand 'Sun Life' --question '照护责任如何影响退休安排？' --output ../../state/first-live-input.json
../../venv/bin/python -m insightbot.signal_desk run --input ../../state/first-live-input.json --mode live --id sunlife-first-live
```

随后在页面输入 `sunlife-first-live` 加载并审稿。模型编辑每轮上限一次，证据上限 50 条、卡片上限 8 张；采集命令每次只读一页。当前总费用仍需通过供应商后台 token 限额约束，应用内的调用次数上限不等于金额预算。超时或结果未知时先检查供应商用量与保留文件，勿盲目换文件名重试。

## 测试范围与后续门槛

本轮应核对持久化恢复、未知证据引用阻断、否决不导出、跨供应商去重、预算上限、缺失凭证显式失败，以及浏览器的载入/运行/审核/下载。供应商真实调用、AI 编辑质量、连续两轮业务审稿与成本基线需要配置后单独验收。

尚不具备：自动千瓜采集、自动反证检索、周期调度、客户账户隔离、自动发送、付费商业 SLA。语义正确性仍需要人工审核，结构校验不能证明所有推断都正确。
