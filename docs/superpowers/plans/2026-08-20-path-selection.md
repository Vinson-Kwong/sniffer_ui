# 数据拷贝路径 + BVH融合输出路径 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为"数据拷贝删除"和"BVH融合"增加可配置的本地保存目录：拷贝路径留空 → 程序 exe 所在目录；输出路径留空 → 压缩包所在目录。

**Architecture:** 纯增量改动。`config_store` 提取公开 `app_base_dir()` 并新增 4 个配置键；`BvhMerger.merge` 增加 `output_dir=None` 可选参数决定产物落盘位置；`app.py` 加两个"条目框+浏览(askdirectory)"栏并接线。`RobotController` 不改（已接收 `local_parent` 且自动建目录）。

**Tech Stack:** Python 3.13、CustomTkinter、pytest（现有栈，无新依赖）

**Spec:** `docs/superpowers/specs/2026-08-20-path-selection-design.md`（已批准）

## Global Constraints

- 空值语义：`data_copy_dir` 空 → `str(app_base_dir())`；`bvh_output_dir` 空 → 压缩包所在目录（现状行为）
- 配置键名固定：`data_copy_dir`、`last_copy_dir`、`bvh_output_dir`、`last_bvh_out_dir`（DEFAULTS 中均为 `""`）
- UI 文案中文：placeholder 分别为 `留空则保存到程序所在目录`、`留空则保存到压缩包所在目录`；标签 `拷贝路径:`、`输出路径:`
- 产物名保持 `<文件夹名>_merge.bvh`，同名旧产物直接覆盖
- 目录不存在时保存前 `mkdir(parents=True, exist_ok=True)`
- 浏览用 `filedialog.askdirectory`（选目录），起始目录记忆上次选择
- 提交信息用仓库现有风格（`feat: ...`），结尾加 `Co-Authored-By: Claude <noreply@anthropic.com>`
- 测试命令统一用 `python -m pytest`（Windows / bash）

---

### Task 1: config_store — `app_base_dir()` + 4 个新配置键

**Files:**
- Modify: `config_store.py`（`DEFAULTS`、`config_path()`、`default_config_path()`，新增 `app_base_dir()`）
- Test: `tests/test_config_store.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: `app_base_dir() -> Path`（frozen → exe 所在目录；否则 → `config_store.py` 所在目录即项目根）。后续任务的 `resolve_copy_dest` 依赖它。`DEFAULTS["data_copy_dir"] / ["last_copy_dir"] / ["bvh_output_dir"] / ["last_bvh_out_dir"]` 均为 `""`。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_config_store.py` 末尾（文件顶部 import 区补 `import sys`、`from pathlib import Path`，并从 `config_store` 导入 `app_base_dir, config_path, default_config_path`）：

```python
# ---- path-selection keys + app_base_dir (2026-08-20 spec) ----

def test_defaults_include_path_selection_keys():
    assert DEFAULTS["data_copy_dir"] == ""
    assert DEFAULTS["last_copy_dir"] == ""
    assert DEFAULTS["bvh_output_dir"] == ""
    assert DEFAULTS["last_bvh_out_dir"] == ""


def test_load_old_config_without_new_keys_uses_blank_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"target_ip": "1.2.3.4"}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["data_copy_dir"] == ""
    assert cfg["bvh_output_dir"] == ""


def test_app_base_dir_is_project_root_in_dev():
    # dev (not frozen): the directory holding config_store.py == repo root
    assert app_base_dir() == Path(__file__).resolve().parent.parent


def test_app_base_dir_is_exe_dir_when_frozen(monkeypatch, tmp_path):
    fake_exe = tmp_path / "dist" / "sniffer_ui.exe"
    fake_exe.parent.mkdir()
    fake_exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)
    assert app_base_dir() == fake_exe.parent


def test_config_paths_live_in_app_base_dir():
    assert config_path() == app_base_dir() / "config.json"
    assert default_config_path() == app_base_dir() / "default_config.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: FAIL — collection ImportError `cannot import name 'app_base_dir'`（其余新测试同理不通过）

- [ ] **Step 3: Write minimal implementation**

`config_store.py` — `DEFAULTS` 末尾追加 4 键（保持既有缩进风格）：

```python
DEFAULTS = {
    "local_ip": "",
    "target_ip": "192.168.1.111",
    "port": 22,
    "username": "robot",
    "password": "MangoTango",
    "last_archive_dir": "",
    "run_command": "cd ~/ats && sudo ./sniffer --bin",
    "bvh_archive": "",
    "bvh_file": "",
    "last_bvh_dir": "",
    "data_copy_dir": "",
    "last_copy_dir": "",
    "bvh_output_dir": "",
    "last_bvh_out_dir": "",
}
```

新增公开函数（放在 `DEFAULTS` 之后、`config_path()` 之前），并让两个 path 函数复用它：

```python
def app_base_dir() -> Path:
    """App base dir: next to the frozen exe, else the project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path() -> Path:
    """config.json lives next to the frozen exe, else next to this source file."""
    return app_base_dir() / "config.json"


def default_config_path() -> Path:
    """default_config.json lives next to the exe/script (the 'factory defaults')."""
    return app_base_dir() / "default_config.json"
```

（原 `config_path` / `default_config_path` 中重复的 frozen 判定体删除，改为上面的单行 return。）

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: 全部 PASS（含原有 9 个测试——重构未改变行为）
Run: `python -m pytest -q`
Expected: 全套 PASS（无回归）

- [ ] **Step 5: Commit**

```bash
git add config_store.py tests/test_config_store.py
git commit -m "feat: config_store adds app_base_dir() and 4 path-selection keys

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: BvhMerger — 可选 `output_dir` 决定产物落盘位置

**Files:**
- Modify: `core/bvh_merger.py`（模块/类 docstring、`merge()`、`_merge_sync()`）
- Test: `tests/test_bvh_merger.py`

**Interfaces:**
- Consumes: 无
- Produces: `BvhMerger.merge(archive, bvh_path, on_done, output_dir=None)`、`_merge_sync(archive_path, bvh_path, output_dir=None)`。`output_dir` 为 `None`/空 → 产物存压缩包旁（现状）；否则存 `Path(output_dir)`（不存在则自动创建）。Task 4 的 UI 以关键字参数 `output_dir=str或None` 调用。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_bvh_merger.py` 末尾（复用现有 `merger` fixture、`_make_source`、`_make_archive`）：

```python
# ---- output_dir (2026-08-20 spec) ----

def test_merge_sync_without_output_dir_saves_next_to_archive(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"x8.bin": b"x"})

    m._merge_sync(str(archive), str(src))  # 不传 output_dir

    assert (tmp_path / "data_merge.bvh").is_file()


def test_merge_sync_output_dir_saves_product_there_and_creates_it(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"x8.bin": b"x"})
    out = tmp_path / "results" / "merged"  # 尚不存在

    m._merge_sync(str(archive), str(src), output_dir=str(out))

    assert (out / "data_merge.bvh").is_file()
    assert not (tmp_path / "data_merge.bvh").exists()  # 不再落在压缩包旁
    assert any(str(out) in line for line in logs)


def test_merge_passes_output_dir_through(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"x8.bin": b"x"})
    out = tmp_path / "out"
    done = threading.Event()
    results = []

    def on_done(ok, error):
        results.append((ok, error))
        done.set()

    m.merge(str(archive), str(src), on_done, output_dir=str(out))
    assert done.wait(timeout=10)
    assert results[0][0] is True
    assert (out / "data_merge.bvh").is_file()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bvh_merger.py -v -k output_dir`
Expected: FAIL — `TypeError: _merge_sync() got an unexpected keyword argument 'output_dir'`（第三个测试经 `merge()` 转发，同样 TypeError）

- [ ] **Step 3: Write minimal implementation**

`core/bvh_merger.py` 四处修改：

(a) 模块 docstring 第 3-4 行改为：

```python
"""Local BVH merge: extract the selected tar.gz archive to a temp dir,
copy the selected bvh in under its original name, run mocap-merge on the
extracted folder, then move the resulting <folder>_merge.bvh to output_dir
(default: next to the archive) and clean up, streaming the tool's output.
```

(b) `BvhMerger` 类 docstring 中 `copies the resulting
    <folder>_merge.bvh next to the archive` 改为 `copies the resulting
    <folder>_merge.bvh to output_dir (default: next to the archive)`。

(c) `merge` 方法签名与转发：

```python
    def merge(self, archive, bvh_path, on_done, output_dir=None):
        """Async entry point from the UI thread."""

        def work():
            try:
                self._merge_sync(archive, bvh_path, output_dir=output_dir)
                self._schedule(lambda: on_done(ok=True, error=None))
            except Exception as e:
                msg = str(e)  # bind before the lambda (except target is cleared on exit)
                self._log(f"[BVH融合失败] {e}\n")
                self._schedule(lambda: on_done(ok=False, error=msg))
        threading.Thread(target=work, daemon=True).start()
```

(d) `_merge_sync` 签名与产物落盘块（末尾）：

```python
    def _merge_sync(self, archive_path, bvh_path, output_dir=None):
```

```python
            produced = folder_path / f"{folder_path.name}_merge.bvh"
            if not produced.is_file():
                raise FileNotFoundError(f"融合成功但未找到产物: {produced}")
            dest_dir = Path(output_dir) if output_dir else archive.parent
            dest_dir.mkdir(parents=True, exist_ok=True)
            saved = dest_dir / produced.name
            shutil.copy2(produced, saved)  # stale product from an earlier run: overwrite
            self._log(f"[BVH融合] 产物已保存: {saved}\n")
            self._log("[BVH融合] 完成\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bvh_merger.py -v`
Expected: 全部 PASS（原有测试即"默认存压缩包旁"的回归覆盖）
Run: `python -m pytest -q`
Expected: 全套 PASS

- [ ] **Step 5: Commit**

```bash
git add core/bvh_merger.py tests/test_bvh_merger.py
git commit -m "feat: BvhMerger saves the product to a configurable output_dir

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 数据拷贝路径栏（app.py）

**Files:**
- Modify: `app.py`（import、模块级 `resolve_copy_dest`、`__init__` 状态、`_build_ui` copyf 块、浏览回调、`_load_config_into_ui`、`_persist_config`、`on_copy_data`）
- Create: `tests/test_path_entries.py`

**Interfaces:**
- Consumes: Task 1 的 `app_base_dir`
- Produces: `app.resolve_copy_dest(raw: str) -> str`（strip 后非空返回之，否则 `str(app_base_dir())`）；控件 `self.copy_dir_entry`（CTkEntry）；回调 `on_browse_copy_dir`；config 键 `data_copy_dir` / `last_copy_dir`

- [ ] **Step 1: Write the failing tests**

新建 `tests/test_path_entries.py`：

```python
"""数据拷贝路径栏 + BVH输出路径栏:恢复、持久化、默认值解析、接线。"""
from types import SimpleNamespace

import app as appmod
from app import resolve_copy_dest
from config_store import app_base_dir


# ---- resolve_copy_dest ----

def test_resolve_copy_dest_blank_falls_back_to_app_base_dir():
    assert resolve_copy_dest("") == str(app_base_dir())
    assert resolve_copy_dest("   ") == str(app_base_dir())


def test_resolve_copy_dest_non_blank_wins():
    assert resolve_copy_dest("D:/data") == "D:/data"
    assert resolve_copy_dest("  D:/data  ") == "D:/data"


# ---- 数据拷贝路径栏 ----

def test_copy_dir_entry_restored_from_config(monkeypatch):
    a = appmod.App()
    try:
        monkeypatch.setattr(appmod, "load_config", lambda: {
            "target_ip": "1.2.3.4", "port": 22, "username": "robot",
            "password": "x", "run_command": "ls", "local_ip": "",
            "data_copy_dir": "D:/mocap", "last_copy_dir": "D:/mocap",
        })
        a._load_config_into_ui()
        assert a.copy_dir_entry.get() == "D:/mocap"
        assert a._last_copy_dir == "D:/mocap"
    finally:
        a.destroy()


def test_persist_config_includes_copy_dir_keys(monkeypatch):
    a = appmod.App()
    try:
        a.copy_dir_entry.delete(0, "end"); a.copy_dir_entry.insert(0, "D:/mocap")
        a._last_copy_dir = "D:/mocap"
        saved = {}
        monkeypatch.setattr(appmod, "save_config", lambda cfg: saved.update(cfg))
        a._persist_config()
        assert saved["data_copy_dir"] == "D:/mocap"
        assert saved["last_copy_dir"] == "D:/mocap"
    finally:
        a.destroy()


def test_on_copy_data_uses_entry_value_then_fallback(monkeypatch):
    a = appmod.App()
    try:
        monkeypatch.setattr(a, "session", SimpleNamespace(connected=True))
        a._set_mocap_dir("/remote/mocap/s1")
        captured = {}

        def fake_copy(remote, local_parent, on_done, on_progress=None):
            captured["remote"] = remote
            captured["local_parent"] = local_parent

        monkeypatch.setattr(a.controller, "copy_mocap_data", fake_copy)
        a.copy_dir_entry.delete(0, "end")
        a.copy_dir_entry.insert(0, "D:/mocap")
        a.on_copy_data()
        a._poll()  # drain the scheduled 目标目录 log
        assert captured["local_parent"] == "D:/mocap"
        assert "D:/mocap" in a.log_view.get("1.0", "end")

        a.copy_dir_entry.delete(0, "end")  # 留空 -> 回退 exe/项目根目录
        a.on_copy_data()
        assert captured["local_parent"] == str(app_base_dir())
    finally:
        a.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_path_entries.py -v`
Expected: FAIL — 模块导入错误 `cannot import name 'resolve_copy_dest'`

- [ ] **Step 3: Write minimal implementation**

`app.py` 六处修改：

(a) import 行改为：

```python
from config_store import app_base_dir, ensure_default_config_file, load_config, restore_defaults, save_config
```

(b) `ctk.set_default_color_theme("blue")` 之后、`class App` 之前加模块级纯函数：

```python
def resolve_copy_dest(raw: str) -> str:
    """数据拷贝目标目录：输入非空用输入（去空白），留空回退到程序所在目录。"""
    text = (raw or "").strip()
    return text or str(app_base_dir())
```

(c) `__init__` 中 `self._last_bvh_dir = ""` 之后加：

```python
        self._last_copy_dir = ""
```

(d) `_build_ui` 中 `copyf` 块（`app.py:129` 起）——标题行与原 `copy_row` 行之间插入新行：

```python
        copyf = ctk.CTkFrame(self); copyf.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(copyf, text="数据拷贝删除", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        copy_dir_row = ctk.CTkFrame(copyf, fg_color="transparent"); copy_dir_row.pack(fill="x", **pad)
        ctk.CTkLabel(copy_dir_row, text="拷贝路径:").pack(side="left")
        self.copy_dir_entry = ctk.CTkEntry(copy_dir_row, width=360,
                                           placeholder_text="留空则保存到程序所在目录")
        self.copy_dir_entry.pack(side="left", padx=8)
        ctk.CTkButton(copy_dir_row, text="浏览", width=70, command=self.on_browse_copy_dir).pack(side="left")
        copy_row = ctk.CTkFrame(copyf, fg_color="transparent"); copy_row.pack(fill="x", **pad)
        # ↓ 原有 拷贝删除按钮/进度条 行保持不变
```

(e) 浏览回调（放在 `on_browse` 之后）：

```python
    def on_browse_copy_dir(self):
        path = filedialog.askdirectory(initialdir=self._last_copy_dir or None)
        if path:
            self.copy_dir_entry.delete(0, "end")
            self.copy_dir_entry.insert(0, path)
            self._last_copy_dir = path
```

(f) `_load_config_into_ui` 中 `self.run_cmd_entry.insert(...)` 行之后加：

```python
        self.copy_dir_entry.delete(0, "end")
        self.copy_dir_entry.insert(0, cfg.get("data_copy_dir", ""))
        self._last_copy_dir = cfg.get("last_copy_dir", "")
```

(g) `_persist_config` 的 `save_config({...})` 中 `"run_command"` 行之后加：

```python
                "data_copy_dir": self.copy_dir_entry.get(),
                "last_copy_dir": self._last_copy_dir,
```

(h) `on_copy_data` 中，两个守卫之后、`self._copying_data = True` 之前加目标解析并打印，最后把 `str(Path.cwd())` 换成 `dest`：

```python
    def on_copy_data(self):
        if not self.session.connected:
            self._log("[数据拷贝] 请先连接目标\n"); return
        if not self._mocap_dir:
            self._log("[数据拷贝] 尚未获取 mocap 目录\n"); return
        dest = resolve_copy_dest(self.copy_dir_entry.get())
        self._log(f"[数据拷贝] 目标目录: {dest}\n")
        self._copying_data = True
        self.copy_progress.set(0)
        self.copy_progress_label.configure(text="0%")
        self._refresh_controls()

        def done(ok, error, archive_path):
            self._copying_data = False
            if ok:
                self.copy_progress.set(1)
                self.copy_progress_label.configure(text="100%（完成）")
            else:
                self.copy_progress_label.configure(text="拷贝失败")
            self._refresh_controls()

        self.controller.copy_mocap_data(
            self._mocap_dir, dest, done,
            on_progress=self._set_copy_progress,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_path_entries.py -v`
Expected: 全部 PASS
Run: `python -m pytest -q`
Expected: 全套 PASS（`test_bvh_ui.py`、`test_app_poll.py` 等不受影响）

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_path_entries.py
git commit -m "feat: 数据拷贝 UI selects copy destination (blank = exe dir); config key data_copy_dir

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: BVH融合输出路径栏（app.py）

**Files:**
- Modify: `app.py`（`__init__` 状态、`_build_ui` mergef 块、浏览回调、`_load_config_into_ui`、`_persist_config`、`on_merge_bvh`）
- Test: `tests/test_path_entries.py`（追加）

**Interfaces:**
- Consumes: Task 1 的配置键、Task 2 的 `merge(..., output_dir=...)`
- Produces: 控件 `self.bvh_output_entry`；回调 `on_browse_bvh_output`；config 键 `bvh_output_dir` / `last_bvh_out_dir`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_path_entries.py` 末尾：

```python
# ---- BVH输出路径栏 ----

def test_bvh_output_entry_restored_from_config(monkeypatch):
    a = appmod.App()
    try:
        monkeypatch.setattr(appmod, "load_config", lambda: {
            "target_ip": "1.2.3.4", "port": 22, "username": "robot",
            "password": "x", "run_command": "ls", "local_ip": "",
            "bvh_output_dir": "D:/out", "last_bvh_out_dir": "D:/out",
        })
        a._load_config_into_ui()
        assert a.bvh_output_entry.get() == "D:/out"
        assert a._last_bvh_out_dir == "D:/out"
    finally:
        a.destroy()


def test_persist_config_includes_bvh_output_keys(monkeypatch):
    a = appmod.App()
    try:
        a.bvh_output_entry.delete(0, "end"); a.bvh_output_entry.insert(0, "D:/out")
        a._last_bvh_out_dir = "D:/out"
        saved = {}
        monkeypatch.setattr(appmod, "save_config", lambda cfg: saved.update(cfg))
        a._persist_config()
        assert saved["bvh_output_dir"] == "D:/out"
        assert saved["last_bvh_out_dir"] == "D:/out"
    finally:
        a.destroy()


def test_on_merge_bvh_passes_output_dir_to_merger(monkeypatch, tmp_path):
    a = appmod.App()
    try:
        archive = tmp_path / "data.tar.gz"; archive.write_bytes(b"")  # 存在且后缀合法
        bvh = tmp_path / "take.bvh"; bvh.write_bytes(b"MOTION")
        a.bvh_archive_entry.delete(0, "end"); a.bvh_archive_entry.insert(0, str(archive))
        a.bvh_file_entry.delete(0, "end"); a.bvh_file_entry.insert(0, str(bvh))
        captured = {}

        def fake_merge(archive, bvh, on_done, output_dir=None):
            captured["output_dir"] = output_dir

        monkeypatch.setattr(a.merger, "merge", fake_merge)
        a.bvh_output_entry.delete(0, "end")
        a.bvh_output_entry.insert(0, "D:/out")
        a.on_merge_bvh()
        assert captured["output_dir"] == "D:/out"

        a._merging = False
        a.bvh_output_entry.delete(0, "end")  # 留空 -> None(默认压缩包所在目录)
        a.on_merge_bvh()
        assert captured["output_dir"] is None
    finally:
        a.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_path_entries.py -v -k bvh_output`
Expected: FAIL — `AttributeError: 'App' object has no attribute 'bvh_output_entry'`

- [ ] **Step 3: Write minimal implementation**

`app.py` 六处修改：

(a) `__init__` 中 `self._last_copy_dir = ""` 之后加：

```python
        self._last_bvh_out_dir = ""
```

(b) `_build_ui` 中 `mergef` 块——`m2`（BVH文件行）与 `m3`（融合按钮行）之间插入：

```python
        m_out = ctk.CTkFrame(mergef, fg_color="transparent"); m_out.pack(fill="x", **pad)
        ctk.CTkLabel(m_out, text="输出路径:").pack(side="left")
        self.bvh_output_entry = ctk.CTkEntry(m_out, width=360,
                                             placeholder_text="留空则保存到压缩包所在目录")
        self.bvh_output_entry.pack(side="left", padx=8)
        ctk.CTkButton(m_out, text="浏览", width=70, command=self.on_browse_bvh_output).pack(side="left")
```

(c) 浏览回调（放在 `on_browse_bvh_file` 之后）：

```python
    def on_browse_bvh_output(self):
        path = filedialog.askdirectory(initialdir=self._last_bvh_out_dir or None)
        if path:
            self.bvh_output_entry.delete(0, "end")
            self.bvh_output_entry.insert(0, path)
            self._last_bvh_out_dir = path
```

(d) `_load_config_into_ui` 中 `self._last_bvh_dir = cfg.get("last_bvh_dir", "")` 行之后加：

```python
        self.bvh_output_entry.delete(0, "end")
        self.bvh_output_entry.insert(0, cfg.get("bvh_output_dir", ""))
        self._last_bvh_out_dir = cfg.get("last_bvh_out_dir", "")
```

(e) `_persist_config` 的 `save_config({...})` 中 `"last_bvh_dir"` 行之后加：

```python
                "bvh_output_dir": self.bvh_output_entry.get(),
                "last_bvh_out_dir": self._last_bvh_out_dir,
```

(f) `on_merge_bvh` 末尾把 `self.merger.merge(archive, bvh, done)` 换成：

```python
        output_dir = self.bvh_output_entry.get().strip()
        self.merger.merge(archive, bvh, done, output_dir=output_dir or None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_path_entries.py -v`
Expected: 全部 PASS
Run: `python -m pytest -q`
Expected: 全套 PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_path_entries.py
git commit -m "feat: BVH融合 UI selects output dir (blank = archive dir); config key bvh_output_dir

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec coverage**: UI 两栏/placeholder/askdirectory/记忆(任务3、4)；`resolve_copy_dest`+`on_copy_data`(任务3)；`output_dir` 参数+自动建目录+默认回归(任务2)；`app_base_dir` 提取+4 键+旧配置兼容(任务1)；错误路径沿用现有 try/except 无需新代码——均已覆盖。
- **Placeholder scan**: 所有步骤含完整代码/命令，无 TBD。
- **Type consistency**: `output_dir=None` 关键字在 Task 2 定义、Task 4 使用一致；`copy_dir_entry`/`bvh_output_entry`/`on_browse_copy_dir`/`on_browse_bvh_output` 命名前后一致；4 个配置键名与 Task 1 DEFAULTS 完全一致。
