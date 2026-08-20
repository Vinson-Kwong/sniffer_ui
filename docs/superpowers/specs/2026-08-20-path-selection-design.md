# 数据拷贝路径与 BVH融合输出路径 设计

日期：2026-08-20
状态：已批准（方案 A）

## 目标

为两个功能增加可配置的本地目录，均为"空值即默认、浏览可选、持久化记忆"：

1. **数据拷贝删除**：第一栏新增"拷贝路径"。留空时，mocap 数据压缩包默认保存到
   程序 exe 所在目录（打包版：`sniffer_ui.exe` 旁边；开发运行：项目根，与
   config.json 同目录的判定逻辑一致）。
2. **BVH融合**：新增"输出路径"栏（BVH文件 与 融合按钮 之间）。留空时，融合产物
   `<文件夹名>_merge.bvh` 默认保存到压缩包所在目录（即现状行为）。

## 非目标

- 不改动远端（机器人侧）的拷贝/清理逻辑。
- 不做输出文件名自定义（产物名仍由 mocap-merge 决定）。
- 不抽通用"路径行"组件、不重构现有三处浏览行（YAGNI）。

## UI

风格与现有区块一致（透明内嵌行 + 条目框 + 70 宽"浏览"按钮）：

```
┌─ 数据拷贝删除 ─────────────────────────────────┐
│ 拷贝路径: [........................] [浏览]   │  ← 新增第一栏
│ [拷贝删除]  [══════进度条══════] 45%           │  ← 现有行
└─────────────────────────────────────────────────┘

┌─ BVH融合 ─────────────────────────────────────┐
│ 压缩包:   [........................] [浏览]   │
│ BVH文件:  [........................] [浏览]   │
│ 输出路径: [........................] [浏览]   │  ← 新增（融合按钮上方）
│ [融合]                                         │
└─────────────────────────────────────────────────┘
```

- 拷贝路径 placeholder：`留空则保存到程序所在目录`；
  输出路径 placeholder：`留空则保存到压缩包所在目录`。
- 浏览按钮：`filedialog.askdirectory`（选目录，天然只列可访问路径），
  起始目录记忆上次选择，结果填入条目框。

## 行为

### 数据拷贝（app.py）

- 目标目录解析为模块级纯函数：`resolve_copy_dest(raw: str) -> str`——
  `raw.strip()` 非空返回其结果，否则返回 `str(app_base_dir())`。便于直接单测。
- `on_copy_data` 把现有写死的 `str(Path.cwd())` 换成
  `resolve_copy_dest(self.copy_dir_entry.get())`；拷贝开始时日志打印目标目录。
- `RobotController.copy_mocap_data` / `_copy_mocap_sync` **不改**：已接收
  `local_parent` 并自动 `mkdir(parents=True, exist_ok=True)`。

### BVH融合（core/bvh_merger.py）

- `BvhMerger.merge(archive, bvh_path, on_done, output_dir=None)` 新增可选参数。
- `_merge_sync` 产物保存位置改为：
  `dest_dir = Path(output_dir) if output_dir else archive.parent`；
  保存前 `dest_dir.mkdir(parents=True, exist_ok=True)`；同名旧产物照旧覆盖。
- `on_merge_bvh` 传 `output_dir=self.bvh_output_entry.get().strip() or None`；
  空值时与现状完全一致（存压缩包旁）。

### 错误处理

- 手动输入不存在的目录：两处都在保存前自动创建（行为一致）。
- 目录创建/写入失败（无权限等）：异常走现有失败路径——日志报
  `[数据拷贝失败]` / `[BVH融合失败]`，进度标签/按钮状态复位，不崩溃。

## 配置持久化

config.json 新增键（`DEFAULTS` 同步补空串，`load_config` 以 DEFAULTS 兜底，
旧配置文件无需迁移）：

| 键 | 含义 |
|---|---|
| `data_copy_dir` | 数据拷贝目标目录（空=默认 exe 目录） |
| `bvh_output_dir` | BVH融合输出目录（空=默认压缩包目录） |
| `last_copy_dir` | 拷贝路径浏览对话框起始目录 |
| `last_bvh_out_dir` | 输出路径浏览对话框起始目录 |

启动恢复到条目框、变更持久化，时机与现有字段一致。

## 模块改动

- `config_store.py`：新增公开 `app_base_dir() -> Path`（frozen → exe 目录，
  否则源码根目录）；`config_path()` / `default_config_path()` 改为复用它；
  `DEFAULTS` 增加上表 4 键。
- `app.py`：两栏 UI、两个浏览回调、`resolve_copy_dest`、config 装载/持久化、
  `on_copy_data` / `on_merge_bvh` 接线。
- `core/bvh_merger.py`：`merge` / `_merge_sync` 的 `output_dir` 参数与产物落盘。

## 测试

- `tests/test_config_store.py`：新键往返；旧 config.json 缺新键时取默认空串。
- UI 接线测试（沿用 `test_bvh_ui.py` 模式）：新两栏从 config 恢复、
  `_persist_config` 含新键、`resolve_copy_dest` 空/非空两分支、
  `on_copy_data` 传给 controller 的目标目录正确（FakeSession 记录参数）。
- `tests/test_bvh_merger.py`：`output_dir=None` 产物落在压缩包旁（回归）；
  `output_dir` 指定时落在该目录、目录不存在时自动创建。
