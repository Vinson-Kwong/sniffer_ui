# Sniffer UI — 设计规格 (Design Spec)

- 日期: 2026-07-24
- 状态: 已批准 (Approved)
- 来源需求: `feature.md`

## 1. 目标

构建一个 Windows 桌面工具，用于对局域网内的机器人（默认 `192.168.1.111`，用户 `robot`）通过 SSH/SCP 进行：连接诊断、程序存在性检查、上传并解压部署包、运行/停止 `~/ats/sniffer` 程序、删除程序。软件记忆上次使用的参数，启动即加载。

## 2. 技术栈

| 关注点 | 选型 |
|---|---|
| 语言 | Python 3.13（本机已装 3.13.3） |
| SSH/SFTP 库 | paramiko 5.0.0（已安装） |
| GUI 框架 | CustomTkinter（现代深色外观，需 pip 安装） |
| 配置 | `config.json`（明文） |
| 打包 | PyInstaller `--onefile --windowed` → `sniffer_ui.exe` |

不使用 Node/Electron（paramiko 已就绪，Python 路径最短）。

## 3. 模块结构

单进程、单窗口，代码按职责分文件，便于测试与维护：

```
sniffer_ui/
├── main.py                # 入口：初始化 CustomTkinter，启动 App
├── app.py                 # App 类：组装 UI、持有 controller、轮询事件队列
├── ui/
│   ├── main_window.py     # 窗口布局与控件
│   └── log_view.py        # 滚动日志区（线程安全写入）
├── core/
│   ├── ssh_session.py     # 封装 paramiko：连接 / 一次性命令 / SFTP 上传 / 交互 shell
│   ├── robot_controller.py# 业务动作：connect、check_program、upload+decompress、run/stop、delete
│   └── net_info.py        # 枚举本机 IPv4（stdlib socket 实现，避免额外依赖）
├── config_store.py        # 读写 config.json
└── resources/             # 图标等（可选）
```

各模块单一职责、接口清晰，可独立测试。

## 4. UI 布局

单窗口，自上而下三个分区 + 底部日志区：

```
┌─ 连接设置 ────────────────────────────────────────┐
│ 本地IP: [192.168.1.10  ▼]    端口: [22]            │
│ 目标IP: [192.168.1.111]                             │
│ 用户名: [robot]               密码: [MangoTango] 👁 │
│                                  [连接]   状态:●未连接│
├─ 部署 ────────────────────────────────────────────┤
│ 压缩包: [................] [浏览]   [上传并解压]     │
│ 程序检查 ~/ats/sniffer:  ✅已存在 / ❌不存在 / ❓未知│
├─ 运行 ────────────────────────────────────────────┤
│ [运行]                [删除 ~/ats/sniffer]          │
├─ 日志 ────────────────────────────────────────────┤
│ [ 实时滚动输出（命令结果 + sniffer 日志）          ]│
└────────────────────────────────────────────────────┘
```

- 本地 IP 下拉：`net_info` 枚举非回环 IPv4，默认选第一个。
- 密码框带 👁 显示/隐藏切换；默认隐藏。
- 按钮 enable/disable 由连接状态驱动（未连接时上传/运行/删除禁用）。
- “运行”按钮在程序运行期间文案切换为“停止”。

## 5. 连接与状态机（线程模型）

- SSH 是阻塞调用，**所有 SSH 动作在 worker 线程执行**，绝不阻塞 UI 线程。
- worker 线程把结果/日志投递到线程安全 `queue.Queue`；UI 线程用 `root.after(100ms, poll)` 周期性消费队列并刷新控件。
- 状态机：

  ```
  DISCONNECTED ──(点击连接)──> CONNECTING ──成功──> CONNECTED
        ▲                           │                    │
        │                           失败                  │ (点击运行)
        └──────────────────────    └─留在 DISCONNECTED   ▼
                                                   PROGRAM_RUNNING
                                                       │ (再点击=Ctrl+C)
                                                       ▼
                                                   CONNECTED
  ```

- `连接` 打开一个持久 `paramiko.SSHClient`，上传/运行/删除复用之；窗口关闭时关闭连接。
- 运行期间额外打开一条持久 `invoke_shell()` 交互通道（见 §7）。

## 6. 各功能行为

### 6.1 连接 + 自动检查程序
- `ssh.connect(host, port, user, password)`。
- 成功后立即执行 `test -f ~/ats/sniffer && echo __EXISTS__ || echo __MISSING__`，据输出更新“程序检查”指示灯（✅/❌）。
- 日志打印连接结果与检查结果；状态点转绿。
- 失败：捕获 `AuthenticationException` / `NoValidConnectionsError` / `socket.error` / `SSHException`，以中文显示，状态点转红，留在 DISCONNECTED。

### 6.2 上传并解压
- 文件选择对话框选本地压缩包（记忆上次目录）。
- SFTP 把文件 put 到远端 `~/ats/`。
- 按扩展名解压（一次性 `exec_command`）：
  - `.tar.gz` / `.tgz` → `tar -xzf <file> -C ~/ats/`
  - `.tar` → `tar -xf <file> -C ~/ats/`
  - `.zip` → `unzip -o <file> -d ~/ats/`（若无 `unzip`，提示安装）
  - 其他 → 日志报错“不支持的压缩格式”
- 解压后刷新“程序检查”指示灯（验证 `~/ats/sniffer` 是否出现）。
- 每步进度/结果写入日志。

### 6.3 运行 / 停止
- 采用**持久交互 shell（invoke_shell）**方案（spec 唯一架构分支，见 §10）。
- 运行：打开 shell 通道，发送 `sudo ~/ats/sniffer --bin\n`。若检测到 `[sudo] password for ...:` 提示，自动回填当前密码并发送。（假设 sudo 口令与登录口令相同；如现场发现不同，可在后续加独立字段，本期用同一密码。）后台读线程持续把 stdout 流式写入日志区。按钮文案切为“停止”，状态 → PROGRAM_RUNNING。
- 停止：在**同一通道**发送 `\x03`（Ctrl+C），等待进程结束（读到 shell 回到提示符），按钮切回“运行”，状态 → CONNECTED。
- 启动失败（命令立即报错/退出码非 0）→ 日志返回结果，按钮保持“运行”。

### 6.4 删除
- `exec_command('rm -f ~/ats/sniffer')`。
- 刷新程序检查指示灯（→ ❌不存在）。
- 结果写入日志。

## 7. 交互 shell 通道的生命周期

- 首次“运行”时惰性打开 `client.invoke_shell()`，后续 stop 复用。
- 通道断开（远端重启等）时自动标记 PROGRAM_RUNNING 结束，提示重连。
- 仅在 CONNECTED/PROGRAM_RUNNING 状态下持有；DISCONNECTED 时关闭。

## 8. 配置文件

- 路径：**与 exe 同目录**（开发期与脚本同目录）。判定方式：打包后用 `sys.executable` 所在目录，开发期用 `__file__` 所在目录（统一封装于 `config_store`）。
- 文件：`config.json`，明文。结构：

  ```json
  {
    "local_ip": "192.168.1.10",
    "target_ip": "192.168.1.111",
    "port": 22,
    "username": "robot",
    "password": "MangoTango",
    "last_archive_dir": ""
  }
  ```

- 时机：启动加载填充输入框；任意参数变更即时写回（保证记忆最新）；窗口关闭时再写一次；文件缺失/损坏时用默认值并重建。

## 9. 错误处理

- 所有 paramiko/网络异常在 worker 线程捕获，转为中文消息投递到日志，绝不弹原生异常、绝不崩溃。
- 操作前的状态守卫：未连接禁用上传/运行/删除；PROGRAM_RUNNING 时禁用“删除”与“上传”（避免运行中改动）。
- 连接中断：状态回退 DISCONNECTED，提示并允许重连。

## 10. 关键设计决策记录

- **运行/停止用持久交互 shell（invoke_shell + `\x03`）**，而非 exec_command+PID+SIGINT。理由：忠实实现“Ctrl+C 退出”，且天然获得 sniffer 实时日志流（用户已确认要实时日志）。
- **config.json 放 exe 同目录、密码明文存储**：用户已确认（内网部署工具，便利优先）。

## 11. 打包

- PyInstaller：`--onefile --windowed --name sniffer_ui`，并用 `--add-data` 打包 CustomTkinter 资源（`customtkinter` 安装目录）。
- 产物：`dist/sniffer_ui.exe`，`config.json` 运行时生成于其同目录。

## 12. 不在范围内（YAGNI）

- 多目标批量管理、保存多个连接配置档案、密钥/公钥认证（本期仅密码）、sniffer 日志保存到文件、自动重连退避策略、国际化（仅中文）。

## 13. 测试策略

- 单元（纯逻辑，可离线测）：`config_store` 读写往返、`net_info` 过滤回环、`robot_controller` 解压命令按扩展名分发、状态机迁移。
- 集成（需机器人/桩）：用一个本地 SSH 桩（如 docker openssh）验证连接/上传/解压/run/stop/delete 端到端。
