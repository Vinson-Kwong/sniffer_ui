# BVH融合 功能设计

日期：2026-08-17
状态：已批准（方案 A）

> **2026-08-17 修订（杀毒误报）**：打包版 `mocap-merge.exe`（PyInstaller、无签名）
> 被 Windows Defender 拦截。改为**源码优先**运行：开发环境下用
> `python -m mocap_merge <文件夹> --verbose`（PYTHONPATH 指向 `merge_app/src`，
> 源码从 github.com/Vinson-Kwong/mocap_merge 克隆）；仅当无解释器（PyInstaller
> 打包的 sniffer_ui.exe）或源码缺失时回退到 exe。requirements.txt 相应新增
> numpy/pyyaml。
>
> **2026-08-17 修订二（拷贝命名）**：原设计"拷贝为 `<stem>_merge.bvh`"与
> mocap_merge 的输入发现规则冲突（`paths.py` 只认 `*BDX.bvh` / `*BDX0709.bvh`
> 结尾的文件名，导致 `missing required input: optical BDX.bvh`）。经确认改为：
> **拷贝保留原文件名**，同名旧拷贝视为同一逻辑输入的过期副本，直接覆盖；
> 工具输出本来就是 `<文件夹名>_merge.bvh`，不会与输入冲突。
>
> **2026-08-17 修订三（打包版进程内运行）**：Defender 同样拦截新编译的未签名
> sniffer_ui.exe 的执行，打包版无法依赖旁置 exe。冻结构建改为把 mocap_merge
> 源码与模板（sample.bvh、bdx_v4.urdf → `<_MEIPASS>/data`）打进包内，
> BVH融合在**进程内**直接调用 `mocap_merge.cli.main()`（stdout/stderr 重定向
> 到日志）。运行器选择顺序：本地源码子进程 `python -m`（开发，隔离崩溃）→
> 进程内调用（打包版/已安装）→ 旁置 exe（最后手段）。sniffer_ui.spec 用
> `pathex=merge_app/src` 解析延迟导入（editable 安装对 PyInstaller 不可见）。

## 目标

在"数据拷贝删除"区块与"日志"区之间新增"BVH融合"区块：用户选择一个文件夹和一个
.bvh 文件，点击"融合"后，把 bvh 文件以 `<原名去扩展>_merge.bvh` 的名字拷贝进文件夹
（不覆盖任何原文件），然后执行 `merge_app\mocap-merge.exe <文件夹路径> --verbose`，
输出流式打印到日志区。

## 非目标

- 不依赖 / 不影响 SSH 连接状态（纯本地操作）。
- 不做进度条、取消按钮。
- 不解析融合结果（只在日志展示 exe 输出与退出码）。

## UI

插入位置：`app.py` `_build_ui()` 中 `copyf`（数据拷贝删除）之后、"日志"标签之前。
风格与现有区块一致（CTkFrame + 粗体标题 + 透明内嵌行）：

```
┌─ BVH融合 ─────────────────────────────────────┐
│ 文件夹:   [____________________] [浏览]        │
│ BVH文件:  [____________________] [浏览]        │
│ [融合]                                        │
└───────────────────────────────────────────────┘
```

## 行为

1. 浏览（文件夹）：`filedialog.askdirectory`，结果填入条目框。
2. 浏览（BVH文件）：`filedialog.askopenfilename`，filetypes 为
   `[("BVH 文件", "*.bvh"), ("所有文件", "*.*")]`（沿用现有浏览按钮的模式）。
3. 融合按钮（始终可用，不需要已连接）：
   - 校验：文件夹是目录、bvh 是文件、exe 存在；任一不满足 → 日志报错并中止。
   - 拷贝：`shutil.copy2(源, 文件夹/<stem>_merge.bvh)`；`<stem>_merge.bvh`
     已存在时直接覆盖（它是本功能自己生成的产物）。
   - 执行：`subprocess.Popen([exe, 文件夹, "--verbose"])`，列表参数、不走 shell；
     stdout/stderr 逐行流式输出到日志区；结束后打印 `[BVH融合] 退出码=N`。
   - 融合期间按钮禁用，结束后（成功或失败）恢复。

## exe 路径解析（core/bvh_merger.py）

```python
def merge_app_exe_path() -> Path:
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent.parent
    return base / "merge_app" / "mocap-merge.exe"
```

开发环境：项目根下的 `merge_app/`；PyInstaller 打包后：`sniffer_ui.exe` 旁边的
`merge_app/`（发版时需随 exe 分发该文件夹）。

## 输出编码

逐行 `decode`：先 UTF-8，`UnicodeDecodeError` 回退 GBK，最终 `errors="replace"`，
避免中文 Windows 下乱码或崩溃。

## 线程模型

沿用现有模式：后台 `threading.Thread`（daemon）执行拷贝 + 子进程读取，
通过注入的 `schedule` 回调把日志/结束事件送回 UI 线程队列。

## 配置持久化

config.json 新增键：`bvh_folder`、`bvh_file`（启动时恢复到条目框，保存时机与
现有字段一致）；另存 `last_bvh_dir` 作为浏览对话框的起始目录。

## 模块与测试

- 新建 `core/bvh_merger.py`：`merge_app_exe_path()`、`merged_copy_name(path)`（纯函数，
  命名规则）、`BvhMerger` 类（`merge(folder, bvh_path, on_done)`）。
- `tests/test_bvh_merger.py`：命名规则、命令参数拼装、拷贝行为（含覆盖自己的
  `_merge.bvh`）、输出解码回退；子进程用临时脚本代替真实 exe。
- `.gitignore` 追加 `merge_app/`（本地二进制工具，与 dist/、config.json 同类）。
