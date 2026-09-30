# Signal Desk 团队测试

2026-09-30｜内部测试环境操作说明。本文描述部署与使用方式；现场验证结果另行记录，不将安装步骤视为验收结果。

## 入口与使用边界

团队入口：`https://192.168.60.97:18878`，仅用于能够访问 Mac mini 所在内网的同事。管理员在 Mac mini 本机仍可使用 `http://127.0.0.1:18876`；远程运维可通过 SSH 隧道访问该本机入口。不要为测试端口设置公网转发。

首次访问内网 HTTPS 时，自签证书会触发浏览器信任提示。由使用者先向管理员核对证书与访问地址，再自行完成浏览器／系统需要的信任操作。不能把忽略证书验证作为日常使用方式。地址改变后，应同时调整网络配置与包含正确地址的证书。

这是有账号访问控制的内部共享工作区。admin 管理测试账号，editor 使用业务表单建立研究任务、查看结果并按分配权限审核。账号初始化及密码变更以应用提供的实际管理入口为准；不要把密码放进链接、群公告或命令参数。共享工作区中的运行资料可被获授权团队成员访问；它不等于针对各客户实施了完整隔离的商用多租户系统。

建议先运行明确标记的离线样例，熟悉 Brief、证据卡、审核与导出；再选择已配置供应商的真实模式。真实数据与模型调用可能计费。未配置、认证失败、无合格结果与离线样例必须保持可辨识。

## Mac mini 目录

| 内容 | 位置 |
| --- | --- |
| 测试根目录 | `~/Applications/SignalDesk-test` |
| 本轮代码 | `releases/20260930` |
| 独立 Python 3.12 环境 | `venv` |
| 原有运行与审核数据 | `state`（沿用，不重建） |
| AI／数据供应商配置 | `config.env`（保留原值） |
| 内网与 TLS 配置 | `network.env` |
| 服务日志 | `logs/service.stdout.log`、`logs/service.stderr.log` |
| 用户启动项 | `~/Library/LaunchAgents/com.mikawang.signal-desk-test.plist` |

`config.env` 与 `network.env` 均为 shell 可读取的环境赋值文件，值含特殊字符时应正确引用。仅由管理员编辑，权限应为 `600`，不提交 Git，不同步到 Obsidian。脚本先加载供应商配置，再加载网络配置；网络文件不应重复定义供应商密钥。

`network.env` 包含下列设置。证书和私钥的真实路径由部署时创建的位置决定，不能保留占位值：

```bash
SIGNAL_DESK_LAN_HOST=192.168.60.97
SIGNAL_DESK_TLS_CERT='/absolute/path/to/test-certificate.pem'
SIGNAL_DESK_TLS_KEY='/absolute/path/to/test-private-key.pem'
```

内网 TLS 监听端口为 `18878`；同一服务保留 localhost `18876`。私钥应仅服务所属用户可读。未配置 TLS 时不能将明文 localhost 服务直接改为内网开放。

## 启动与维护

本轮使用用户级 LaunchAgent，不安装全局依赖。它在所属 macOS 用户登录后启动并在进程退出后重启；**不会在无人登录时自动启动**。退出该用户会话可能结束服务，锁屏与退出登录不是一回事。Mac mini 睡眠或断网时团队也无法访问。

部署人员先停止旧的手工服务，确认端口释放；不要让旧脚本与 LaunchAgent 同时启动。然后执行：

```bash
bash ~/Applications/SignalDesk-test/releases/20260930/scripts/signal-desk-service.sh install
bash ~/Applications/SignalDesk-test/releases/20260930/scripts/signal-desk-service.sh start
bash ~/Applications/SignalDesk-test/releases/20260930/scripts/signal-desk-service.sh status
```

`install` 只生成属于本测试环境的用户 plist，凭证从运行时文件读取，不写入 plist 或进程命令行。`start` 注册服务；启动命令成功不等于应用健康，需继续检查 `status`、登录和业务操作。

修改 env 后用 `stop` 再 `start`。`start` 会恢复该测试启动项的启用状态。运行 `status` 时，LaunchAgent 状态与 localhost `/health` 应都正常；还应由团队浏览器验证 HTTPS 登录、创建研究任务、查看卡片、审核和登出。认证问题只能在实际入口完成验证，健康页不能替代它。

## 回退与数据保留

```bash
bash ~/Applications/SignalDesk-test/releases/20260930/scripts/signal-desk-service.sh stop
```

`stop` 卸载当前进程并禁用后续登录自启，保留代码、env、证书、账号和研究／审核数据；不会删除旧运行记录。之后需要恢复时执行同一脚本 `start`。若需回到旧代码，先核对该版本对当前账号和状态格式的兼容性，不直接把旧的无认证服务开放到内网。

## 团队试跑验收

- 未登录访问受保护页面会进入登录流程；登出后原会话不能继续提交操作。
- 管理员与编辑账号权限符合界面约定；错误密码不暴露用户存在性或凭证。
- 表单能提交一个品牌问题，生成来源可追溯的卡片；离线与真实模式区分清楚。
- 审核前后状态变化正确；重启服务后原任务与审核状态仍可读取。
- 页面不输出 API key、token 或私钥；日志不记录认证头／完整含密钥请求 URL。
- 从另一台内网设备通过 HTTPS 验证实际访问。服务绑定与健康检查不能替代此项。

初版的共享工作区适合内部编辑评估。客户直接登录、跨客户权限隔离、公网发布及正式交付 SLA 属于后续独立验收范围。
