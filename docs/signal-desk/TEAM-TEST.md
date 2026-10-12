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


## 首次登录

初始管理员账号为 `admin`。随机初始密码保存在 Mac mini 的 `state/bootstrap-admin.txt`，权限600。Mika本机交付副本为 `/Users/mikawang/Applications/SignalDesk-access/admin-initial-password.txt`；文件不进入Git或Obsidian。登录后可通过“修改我的密码”更新；所有旧会话随之失效，服务器的bootstrap文件被移除。本机交付副本随即过期，不应作为长期凭证来源。

管理员在“管理”创建同事账号。角色“研究与审稿”可创建研究、查看共享结果、修改卡片、批准或否决；不能管理账号。当前没有为每个客户单独划分可见范围。

公开测试证书：`/Users/mikawang/Applications/SignalDesk-access/macmini-test-cert.cer`。SHA256指纹：`8C:69:63:4F:CC:5A:98:D4:BC:61:99:27:66:89:6A:13:96:D1:86:C1:3C:A7:25:44:6A:A7:9A:CE:85:1D:D7:51`。证书包含 `mika-macmini.local` 与 `192.168.60.97`；私钥只留在测试机。此轮未修改用户设备的系统信任设置。导入与信任由使用者在自己的设备完成；不应绕过不同证书的警告。

## 界面验收说明

界面以完整研究设置概念图为基准，保留深绿/暖白色、双栏布局、表单字段顺序、右侧调用范围及主次按钮。实际实现增加“已保存的研究”和“使用Sun Life模板”以承接真实操作，并以已登录账号替代概念中的姓名。文案、排版、边距、控件、色彩和移动端换行均通过截图检查。业务字段、卡片内容与来源链接由代码原生渲染。

由于本会话没有Browser插件/skill，使用已有Playwright与Chrome验证。桌面1440×1050、手机390×844；历史回放“计划确认→后台运行→修改卡片→批准→下载”通过，手机无横向溢出、无页面脚本错误。未登录数据接口401、无CSRF写入403、编辑账号无管理员权限、退出后会话失效均验证。内网证书另以 `curl --cacert` 验证；自动化浏览器仅在隔离QA上下文允许自签证书，不表示已替员工完成设备信任。

## 2026-09-30 实测结果

- 本地相关回归70项通过；部署机 Signal Desk 模块34项通过。
- 从 Mika 的另一台电脑经局域网 HTTPS 登录成功，Secure cookie、20条证据和3张卡片可正常读取，页面无脚本错误。
- 主动结束服务进程后，LaunchAgent 自动恢复（PID 31035 → 31630）；重新登录后研究结果保持。未执行整机重启测试。
- 本轮真实采集一次返回20条证据。第一次AI调用达到输出上限；修复后复用已保存的同一批证据，未重复采集，第二次AI调用正常生成3张待审卡片（3,917 tokens）。全轮为1次搜索、2次AI调用。
- 恢复结果：`team-live-20260930-recovered`，保持待人工审核，未批准或对外发送。初次失败记录保留。
- GLM 5.3模型默认使用低推理强度，精简传入模型的重复快照；完整证据仍保留在研究记录。能力依据：[GLM 官方说明](https://github.com/zai-org/GLM-5/blob/main/README.md)。其他模型不自动添加该参数。
