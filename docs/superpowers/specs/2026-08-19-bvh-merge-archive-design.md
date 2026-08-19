# BVH融合:文件夹输入改为 tar.gz 压缩包 设计

日期：2026-08-19
状态：已批准（方案 A）

## 背景

BVH融合目前要求用户选择一个**文件夹**（`askdirectory`），把 bvh 拷进去后执行
mocap-merge。而「数据拷贝删除」从机器人取回的数据是压缩包：远端
`tar -czf <临时包> -C <父目录> <目录名>`，下载后得到 `<目录名>-<uuid>.tar.gz`
（`core/robot_controller.py`）。用户需要先手动解压才能融合。

本次把「文件夹」输入改为**压缩包**输入，格式与数据拷贝的产出严格对应：
仅 `.tar.gz` / `.tgz`。融合后把产物拷回压缩包旁边，不在磁盘留解压垃圾。

## 目标

- 「文件夹:」行改为「压缩包:」，浏览对话框只允许选 `.tar.gz` / `.tgz`。
- 融合流程自动完成：解压 → 拷入 bvh → 执行 mocap-merge → 产物拷回压缩包
  旁边 → 清理解压临时目录。
- 纯本地操作，不依赖 SSH 连接状态（不变）。

## 非目标

- 不支持 zip / 纯 tar（数据拷贝不产出这两种格式）。
- 不做解压进度条、取消按钮。
- 不迁移旧配置键 `bvh_folder` 的值。

## 方案选择

- **方案 A（采纳）：解压逻辑收进 `BvhMerger`**。对外接口从
  `merge(folder, bvh, on_done)` 改为 `merge(archive, bvh, on_done)`，内部完成
  解压、定位融合文件夹、融合、产物回拷、临时清理。业务全在 core 层可独立
  测试，UI 保持薄。
- 方案 B（否决）：UI 层解压、merger 不变 —— 业务逻辑落入 app.py，与现有
  「controller/merger 承担业务、app.py 只做调度」的分层相悖。
- 方案 C（否决）：独立解压模块 —— 一个 `tarfile` 调用不值得单独成模块。

## UI（app.py）

- `m1` 行：标签「文件夹:」→「压缩包:」，控件 `bvh_folder_entry` →
  `bvh_archive_entry`。
- 浏览：`filedialog.askopenfilename`，filetypes 仅
  `[("压缩包", "*.tar.gz *.tgz")]`（不给"所有文件"回退，选择强制为压缩包）；
  `initialdir` 沿用 `last_bvh_dir`，选择后更新之。
- 「BVH文件」行、融合按钮位置与禁用逻辑不变。
- `on_merge_bvh` 前置校验（日志报错并中止）：
  - 未填 → `[BVH融合] 请先选择压缩包(tar.gz)`
  - 文件不存在 → `[BVH融合] 压缩包不存在: <路径>`
  - 扩展名不符 → `[BVH融合] 仅支持 tar.gz/tgz 压缩包: <路径>`

## BvhMerger 行为（core/bvh_merger.py）

`_merge_sync(archive_path, bvh_path)` 流程：

1. **校验**：压缩包是文件且以 `.tar.gz` / `.tgz` 结尾；bvh 是文件。运行器
   可用性检查不变（本地源码 / 进程内 / 旁置 exe）。
2. **解压**：`tempfile.TemporaryDirectory()` 中
   `tarfile.open(archive, mode="r:gz").extractall(tmp, filter="data")`。
   `filter="data"` 防路径穿越（Python 3.13，参数可用）。
3. **定位融合文件夹**：tmp 下恰好一个条目且是目录 → 该目录（对应数据拷贝
   `tar -C <父目录> <目录名>` 的单顶层目录结构）；否则（散文件）→ tmp 本身。
4. **拷入 bvh**：`shutil.copy2(bvh, 文件夹/<原名>)`，命名规则不变
   （mocap_merge 靠 `*BDX.bvh` / `*BDX0709.bvh` 后缀发现输入，必须保留原名，
   同名过期副本直接覆盖）。
5. **执行 mocap-merge**：运行器选择顺序、`--verbose`、输出流式解码
   （UTF-8→GBK 回退）、退出码检查全部不变。
6. **产物回拷**：成功后把 `<文件夹名>_merge.bvh`（mocap-merge 默认输出在融合
   文件夹内，`cli.py:51`）`shutil.copy2` 到**压缩包所在目录**；同名旧产物
   直接覆盖（与本功能"过期副本覆盖"约定一致）。
7. **清理**：`with TemporaryDirectory` 退出自动删除临时目录（成功、失败都
   清理）；融合失败时不在压缩包旁边留下任何文件。

## 日志

沿用 `[BVH融合]` 前缀：

- `[BVH融合] 解压 <压缩包名> → 临时目录`
- `[BVH融合] 融合文件夹: <路径>`
- `[BVH融合] 产物已保存: <压缩包旁的 _merge.bvh 路径>`

## 配置（config_store.py）

- `DEFAULTS` 与持久化键：`bvh_folder` → `bvh_archive`。
- 旧 config.json 中的 `bvh_folder` 不迁移：`load_config` 以 DEFAULTS 为底、
  逐键覆盖，未知键自然失效；`save_config` 只写入新键。
- `last_bvh_dir` 语义不变（压缩包与 bvh 两个浏览对话框共用的起始目录）。

## 线程模型

不变：`merge()` 起 daemon `threading.Thread`，日志/结束事件经注入的
`schedule` 回调送回 UI 线程。解压耗时（可达 GB 级 tar.gz）发生在该后台线程，
不阻塞 UI；无进度条（非目标）。

## 测试

- `tests/test_bvh_merger.py`：
  - fixture：tmp 目录里造 `<目录>/*BDX.bvh` 打成 tar.gz；
  - 单顶层目录 → 融合文件夹定位到该目录、bvh 拷入保留原名；
  - 散文件结构 → 融合文件夹为解压根；
  - 产物回拷到压缩包旁边、同名旧产物被覆盖；
  - 结束后临时目录已删除（目录名不复存在）；
  - 非 tar.gz / 不存在 → 报错信息；
  - 现有 `copy_dest_name`、解码回退、运行器选择测试保持通过。
- `tests/test_bvh_ui.py`：入口控件改名后的取值/持久化（`bvh_archive`）、
  校验日志文案；`tests/test_app_poll.py` 中涉及 `bvh_folder_entry` 的引用
  同步改名。
