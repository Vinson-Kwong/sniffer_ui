# BVH融合压缩包输入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BVH融合从「选文件夹」改为「选 tar.gz 压缩包」：自动解压到临时目录 → 拷入 bvh → 跑 mocap-merge → 产物拷回压缩包旁边 → 清理临时目录。

**Architecture:** 解压/定位/回拷/清理全部收进 `core/bvh_merger.py` 的 `_merge_sync`（对外签名从 folder 换成 archive）；`app.py` 只换一行控件与对话框；配置键 `bvh_folder` → `bvh_archive`。设计文档：`docs/superpowers/specs/2026-08-19-bvh-merge-archive-design.md`。

**Tech Stack:** Python 3.13 标准库（`tarfile`、`tempfile`、`shutil`），无新增第三方依赖。customtkinter UI，pytest 测试。

## Global Constraints

- 仅支持 `.tar.gz` / `.tgz`（小写比较），与数据拷贝 `tar -czf` 的产出严格对应；不支持 zip / 纯 tar。
- 解压必须用 `tarfile.open(..., mode="r:gz").extractall(path, filter="data")`（防路径穿越）。
- 拷入的 bvh 必须保留原文件名（mocap_merge 靠 `*BDX.bvh` / `*BDX0709.bvh` 后缀发现输入）——`copy_dest_name` 不变。
- 产物 `<文件夹名>_merge.bvh` 拷到压缩包所在目录，同名旧产物覆盖；失败时不在压缩包旁留任何文件。
- 临时目录用 `tempfile.TemporaryDirectory(prefix="bvh-merge-")`，成功失败都要清理。
- 日志前缀 `[BVH融合] `，文案用中文，与现有一致。
- 测试命令：`python -m pytest tests/<file> -v`（Windows bash，工作目录 = 仓库根 E:\work\sniffer_ui）。
- mocap-merge 运行器选择（本地源码子进程 → 进程内 → 旁置 exe）、`--verbose`、UTF-8→GBK 解码回退全部不动。

---

### Task 1: 纯函数 `is_supported_archive` / `merge_dir_in_extracted`

**Files:**
- Modify: `core/bvh_merger.py`（在 `copy_dest_name` 之后新增两个模块级函数 + 常量）
- Test: `tests/test_bvh_merger.py`

**Interfaces:**
- Consumes: 无（纯函数，仅标准库）。
- Produces: `is_supported_archive(path) -> bool`（str/Path 均可）；`merge_dir_in_extracted(root: Path) -> Path`；常量 `ARCHIVE_SUFFIXES = (".tar.gz", ".tgz")`。Task 2/3 直接使用。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/test_bvh_merger.py`（放在 `test_copy_dest_name_keeps_original_name` 一组纯函数测试之后、`# ---- BvhMerger ----` 之前；同时把文件顶部 import 改为）：

```python
from core.bvh_merger import (
    build_merge_command,
    copy_dest_name,
    decode_output,
    is_supported_archive,
    merge_dir_in_extracted,
    merge_app_exe_path,
)
```

```python
def test_is_supported_archive_accepts_tar_gz_family_only():
    assert is_supported_archive("D:/data-abc.tar.gz") is True
    assert is_supported_archive("D:/data.tgz") is True
    assert is_supported_archive("D:/DATA.TAR.GZ") is True  # case-insensitive
    assert is_supported_archive("D:/data.zip") is False
    assert is_supported_archive("D:/data.tar") is False
    assert is_supported_archive("D:/take.bvh") is False
    assert is_supported_archive("") is False


def test_merge_dir_in_extracted_picks_single_top_level_dir(tmp_path):
    # 数据拷贝打包结构: tar -czf <pkg> -C <父目录> <目录名> -> 单顶层目录
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x8.bin").write_bytes(b"x")
    assert merge_dir_in_extracted(tmp_path) == tmp_path / "data"


def test_merge_dir_in_extracted_falls_back_to_root_for_loose_files(tmp_path):
    (tmp_path / "a.bvh").write_bytes(b"a")
    (tmp_path / "b.bin").write_bytes(b"b")
    assert merge_dir_in_extracted(tmp_path) == tmp_path


def test_merge_dir_in_extracted_single_file_falls_back_to_root(tmp_path):
    (tmp_path / "a.bvh").write_bytes(b"a")
    assert merge_dir_in_extracted(tmp_path) == tmp_path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bvh_merger.py -v -k "is_supported_archive or merge_dir_in_extracted"`
Expected: FAIL with `ImportError: cannot import name 'is_supported_archive'`

- [ ] **Step 3: Implement the helpers**

`core/bvh_merger.py` 顶部 import 块补两行（保持字母序）：`import tarfile`、`import tempfile`（本任务先加 `tarfile` 之外的也行，Task 2 会用到 `tempfile`；一并加上无害）。

在 `copy_dest_name` 函数之后新增：

```python
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz")


def is_supported_archive(path) -> bool:
    """数据拷贝产出 tar.gz（远端 tar -czf）；BVH融合只接受这一族压缩包。"""
    return str(path).lower().endswith(ARCHIVE_SUFFIXES)


def merge_dir_in_extracted(root: Path) -> Path:
    """The folder mocap-merge runs on inside a fresh extraction `root`:
    the single top-level directory (数据拷贝 packs with -C <parent> <name>),
    or `root` itself for flat archives of loose files."""
    entries = list(root.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return root
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bvh_merger.py -v`
Expected: 全部 PASS（含原有测试）

- [ ] **Step 5: Commit**

```bash
git add core/bvh_merger.py tests/test_bvh_merger.py
git commit -m "feat: add archive suffix check and merge-dir resolution helpers"
```

---

### Task 2: `_merge_sync` 改为压缩包流程（解压 → 融合 → 产物回拷 → 清理）

**Files:**
- Modify: `core/bvh_merger.py`（模块/类 docstring、`merge()` 参数名、`_merge_sync` 整体重写）
- Test: `tests/test_bvh_merger.py`（fake exe 产出 `_merge.bvh`；folder 型测试全部改造成 archive 型）

**Interfaces:**
- Consumes: Task 1 的 `is_supported_archive`、`merge_dir_in_extracted`；既有 `copy_dest_name`、`_runner_kind`、`_resolve_runner`、`_run_inprocess`、`decode_output`。
- Produces: `BvhMerger.merge(archive, bvh_path, on_done)` 与 `_merge_sync(archive_path, bvh_path)` —— 第一个参数从文件夹路径变为 **tar.gz 压缩包路径**。Task 3 的 `app.py` 按此调用。
- 产物位置：`<压缩包所在目录>/<融合文件夹名>_merge.bvh`；mocap-merge 默认输出在融合文件夹内（`cli.py:51`: `Path(data_dir)/f"{data_dir.name}_merge.bvh"`）。

- [ ] **Step 1: Rewrite the failing tests**

`tests/test_bvh_merger.py` 的 BvhMerger 部分整体改造：

(a) `# ---- BvhMerger ----` 区的 import 区补 `import tarfile`。

(b) `make_fake_exe` 换成会产出 `_merge.bvh`、并回显拷入的 `take.bvh` 内容的版本（测试靠它观察"工具看到了新拷贝"和产物回拷）：

```python
def make_fake_exe(directory: Path) -> Path:
    """A stand-in mocap exe: echoes its first arg, cats the copied-in
    take.bvh (so tests can see WHICH copy the tool saw), writes the
    <folder>_merge.bvh product, exits 3 if a FAIL file sits inside the
    target folder."""
    if os.name == "nt":
        exe = directory / "fake-mocap-merge.bat"
        exe.write_bytes(
            b"@echo off\r\n"
            b"if exist \"%~1\\FAIL\" exit /b 3\r\n"
            b"if \"%~2\"==\"--verbose\" echo merge-ok %~1\r\n"
            b"type \"%~1\\take.bvh\" 2>nul\r\n"
            b"copy nul \"%~1\\%~n1_merge.bvh\" >nul\r\n"
            b"exit /b 0\r\n"
        )
        return exe
    exe = directory / "fake-mocap-merge.sh"
    exe.write_text(
        '#!/bin/sh\n'
        'if [ -f "$1/FAIL" ]; then exit 3; fi\n'
        'if [ "$2" = "--verbose" ]; then echo "merge-ok $1"; fi\n'
        'cat "$1/take.bvh" 2>/dev/null\n'
        ': > "$1/$(basename "$1")_merge.bvh"\n'
        'exit 0\n',
        encoding="ascii",
    )
    exe.chmod(0o755)
    return exe
```

(c) 新增打包 helper（放在 `_make_source` 后）：

```python
def _make_archive(tmp_path, folder_name="data", files=None) -> Path:
    """Pack tmp_path/folder_name (+files dict) into tmp_path/<folder_name>.tar.gz,
    mirroring 数据拷贝's `tar -czf <pkg> -C <parent> <name>` single top-level dir."""
    folder = tmp_path / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in (files or {}).items():
        (folder / name).write_bytes(content)
    archive = tmp_path / f"{folder_name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(folder, arcname=folder_name)
    return archive


def _temp_folder_from_logs(logs) -> Path:
    """The 融合文件夹 path the merger logged (the temp dir is gone by the
    time the assertion runs, so we can only recover it from the log)."""
    line = next(l for l in logs if "融合文件夹" in l)
    return Path(line.split(":", 1)[1].strip())
```

(d) 删掉旧的 `test_merge_sync_copies_bvh_under_original_name_and_runs_exe`、`test_merge_sync_overwrites_stale_same_name_copy`、`test_merge_sync_raises_on_exe_failure`、`test_merge_sync_validates_inputs`，换成：

```python
def test_merge_sync_extracts_archive_copies_bvh_and_runs_exe(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"optical-BDX.bvh": b"optical"})

    m._merge_sync(str(archive), str(src))

    assert (tmp_path / "data_merge.bvh").is_file(), \
        f"product not copied next to the archive: {logs}"
    assert any("解压" in line for line in logs)
    assert any("融合文件夹" in line for line in logs)
    assert any("已拷贝" in line for line in logs)
    assert any("merge-ok" in line for line in logs), f"exe output not streamed: {logs}"
    assert any("退出码=0" in line for line in logs)
    assert any("产物已保存" in line for line in logs)
    assert any("完成" in line for line in logs)


def test_merge_sync_overwrites_stale_same_name_copy_inside_archive(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path, content=b"new-content")
    archive = _make_archive(tmp_path, "data", {"take.bvh": b"old"})  # stale copy

    m._merge_sync(str(archive), str(src))

    # the fake exe cats the copied-in take.bvh: the tool saw the fresh copy
    assert "new-content" in "".join(logs)


def test_merge_sync_overwrites_stale_product_next_to_archive(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"x8.bin": b"x"})
    (tmp_path / "data_merge.bvh").write_bytes(b"stale product")

    m._merge_sync(str(archive), str(src))

    assert (tmp_path / "data_merge.bvh").read_bytes() == b""  # replaced by fresh product


def test_merge_sync_cleans_up_temp_dir(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {})

    m._merge_sync(str(archive), str(src))

    temp_folder = _temp_folder_from_logs(logs)
    assert temp_folder.parent.name.startswith("bvh-merge-")
    assert not temp_folder.parent.exists()  # whole temp root removed


def test_merge_sync_raises_on_exe_failure_and_cleans_up(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {"FAIL": b""})  # ask exe to exit 3

    with pytest.raises(RuntimeError, match="退出码=3"):
        m._merge_sync(str(archive), str(src))
    assert any("退出码=3" in line for line in logs)
    assert not _temp_folder_from_logs(logs).parent.exists()
    # a failed merge must not leave a product next to the archive
    assert not (tmp_path / "data_merge.bvh").exists()


def test_merge_sync_uses_extraction_root_for_flat_archive(merger, tmp_path):
    m, logs = merger
    src = _make_source(tmp_path)
    archive = tmp_path / "flat.tar.gz"
    staging = tmp_path / "staging"; staging.mkdir()
    (staging / "optical-BDX.bvh").write_bytes(b"o")
    (staging / "x8.bin").write_bytes(b"x")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staging / "optical-BDX.bvh", arcname="optical-BDX.bvh")
        tar.add(staging / "x8.bin", arcname="x8.bin")

    m._merge_sync(str(archive), str(src))

    folder = _temp_folder_from_logs(logs)
    assert folder.name.startswith("bvh-merge-")  # the extraction root itself
    assert (tmp_path / f"{folder.name}_merge.bvh").is_file()


def test_merge_sync_validates_inputs(merger, tmp_path):
    m, _logs = merger
    src = _make_source(tmp_path)
    good = _make_archive(tmp_path, "data", {})
    zip_like = tmp_path / "data.zip"; zip_like.write_bytes(b"PK")

    with pytest.raises(ValueError, match="压缩包不存在"):
        m._merge_sync(str(tmp_path / "missing.tar.gz"), str(src))
    with pytest.raises(ValueError, match="仅支持 tar.gz/tgz"):
        m._merge_sync(str(zip_like), str(src))
    with pytest.raises(ValueError, match="BVH 文件不存在"):
        m._merge_sync(str(good), str(tmp_path / "missing.bvh"))
    missing_exe = BvhMerger(lambda fn: fn(), lambda s: None,
                            exe_path=tmp_path / "nope.exe",
                            source_dir=tmp_path / "no-src",
                            allow_inprocess=False)
    with pytest.raises(ValueError, match="未找到"):
        missing_exe._merge_sync(str(good), str(src))
```

(e) 两个集成测试（inprocess / real source）改为压缩包输入，去掉对临时文件夹内容的断言（文件夹已删），用"已拷贝"日志证明拷贝先于工具执行：

```python
def test_merge_sync_inprocess_runs_cli_and_surfaces_missing_input_error(tmp_path):
    """Integration: real installed mocap_merge, executed in-process on an
    empty extracted folder. Errors must reach the log; no subprocess involved."""
    logs = []
    m = BvhMerger(lambda fn: fn(), logs.append,
                  exe_path=tmp_path / "nope.exe",
                  source_dir=tmp_path / "no-src")
    if m._runner_kind() != "inprocess":
        pytest.skip("mocap_merge not installed in this interpreter")
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {})

    with pytest.raises(RuntimeError, match="退出码=1"):
        m._merge_sync(str(archive), str(src))

    assert any("已拷贝" in line for line in logs)  # copy happened before the tool ran
    assert any("missing required input" in line for line in logs)
    assert any("进程内" in line for line in logs)
    assert any("退出码=1" in line for line in logs)
```

```python
def test_merge_sync_runs_real_source_and_surfaces_missing_input_error(tmp_path):
    """Integration: run the real mocap_merge source (repo merge_app/src) via
    python -m on an empty extracted folder."""
    repo_src = Path(__file__).resolve().parent.parent / "merge_app" / "src"
    if not (repo_src / "mocap_merge" / "__init__.py").is_file():
        pytest.skip("mocap_merge source not cloned")
    logs = []
    m = BvhMerger(lambda fn: fn(), logs.append, exe_path=tmp_path / "nope.exe",
                  source_dir=repo_src)
    src = _make_source(tmp_path)
    archive = _make_archive(tmp_path, "data", {})

    with pytest.raises(RuntimeError, match="退出码=1"):
        m._merge_sync(str(archive), str(src))

    assert any("已拷贝" in line for line in logs)
    assert any("missing required input" in line for line in logs)
    assert any("退出码=1" in line for line in logs)
```

(f) `test_merge_reports_failure_through_on_done` 末尾断言改为：

```python
    m.merge(str(tmp_path / "missing.tar.gz"), str(tmp_path / "x.bvh"), on_done)
    assert done.wait(timeout=5)
    ok, error = results[0]
    assert ok is False
    assert "压缩包不存在" in error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bvh_merger.py -v`
Expected: 新 archive 测试 FAIL（`_merge_sync` 还在要求文件夹 —— `ValueError: 文件夹不存在` 或断言失败）；Task 1 与 runner-kind 等未改动测试 PASS

- [ ] **Step 3: Implement the archive flow in `core/bvh_merger.py`**

(a) 模块 docstring（第 1-2 行）改为：

```python
"""Local BVH merge: extract the selected tar.gz archive to a temp dir,
copy the selected bvh in under its original name, run mocap-merge on the
extracted folder, then move the resulting <folder>_merge.bvh next to the
archive and clean up, streaming the tool's output.
```

（后续 Runner selection 段落不动。）

(b) 类 docstring（`class BvhMerger` 下）改为：

```python
    """Extracts the tar.gz archive, copies the bvh in under its original
    name, runs mocap-merge on the extracted folder, copies the resulting
    <folder>_merge.bvh next to the archive, and cleans up the temp dir —
    streaming output through `log`."""
```

(c) `merge()` 签名与首行（参数 folder → archive）：

```python
    def merge(self, archive, bvh_path, on_done):
        """Async entry point from the UI thread."""

        def work():
            try:
                self._merge_sync(archive, bvh_path)
                self._schedule(lambda: on_done(ok=True, error=None))
            except Exception as e:
                msg = str(e)  # bind before the lambda (except target is cleared on exit)
                self._log(f"[BVH融合失败] {e}\n")
                self._schedule(lambda: on_done(ok=False, error=msg))
        threading.Thread(target=work, daemon=True).start()
```

(d) `_merge_sync` 整体替换为：

```python
    def _merge_sync(self, archive_path, bvh_path):
        archive = Path(archive_path)
        if not archive.is_file():
            raise ValueError(f"压缩包不存在: {archive_path}")
        if not is_supported_archive(archive):
            raise ValueError(f"仅支持 tar.gz/tgz 压缩包: {archive_path}")
        src = Path(bvh_path)
        if not src.is_file():
            raise ValueError(f"BVH 文件不存在: {bvh_path}")
        kind = self._runner_kind()
        if kind == "exe" and not self._exe.is_file():
            raise ValueError(
                f"未找到 {self._exe}（也可以 pip 安装 mocap_merge，"
                f"或把源码放到 {self._source_dir}）"
            )
        with tempfile.TemporaryDirectory(prefix="bvh-merge-") as tmp:
            extract_root = Path(tmp)
            self._log(f"[BVH融合] 解压 {archive.name} → 临时目录\n")
            with tarfile.open(archive, mode="r:gz") as tar:
                tar.extractall(extract_root, filter="data")
            folder_path = merge_dir_in_extracted(extract_root)
            self._log(f"[BVH融合] 融合文件夹: {folder_path}\n")
            dest = folder_path / copy_dest_name(src)
            # dest may be a stale copy packed inside the archive:
            # overwriting it is an update of the same logical input.
            shutil.copy2(src, dest)
            self._log(f"[BVH融合] 已拷贝 {src.name} -> {dest}\n")

            if kind == "inprocess":
                code = self._run_inprocess(folder_path)
            else:
                prefix, env, _must_exist = self._resolve_runner()
                self._log(f"[BVH融合] 执行: {' '.join(prefix)} {folder_path} --verbose\n")
                proc = subprocess.Popen(
                    prefix + [str(folder_path), "--verbose"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                )
                for raw in proc.stdout:
                    self._log(decode_output(raw))
                code = proc.wait()

            self._log(f"[BVH融合] 退出码={code}\n")
            if code != 0:
                raise RuntimeError(f"mocap-merge 退出码={code}")
            produced = folder_path / f"{folder_path.name}_merge.bvh"
            if not produced.is_file():
                raise FileNotFoundError(f"融合成功但未找到产物: {produced}")
            saved = archive.parent / produced.name
            shutil.copy2(produced, saved)  # stale product from an earlier run: overwrite
            self._log(f"[BVH融合] 产物已保存: {saved}\n")
            self._log("[BVH融合] 完成\n")
```

(e) 确认 import 块含 `import tarfile` 与 `import tempfile`（Task 1 已加则跳过）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bvh_merger.py -v`
Expected: 全部 PASS（含 Task 1 纯函数、runner-kind、解码测试）

- [ ] **Step 5: Commit**

```bash
git add core/bvh_merger.py tests/test_bvh_merger.py
git commit -m "feat: BVH merge runs on a tar.gz archive (extract, merge, retrieve product)"
```

---

### Task 3: 配置键改名 + app.py 接线 + UI 测试

**Files:**
- Modify: `config_store.py:16`（DEFAULTS 键改名）
- Modify: `default_config.json:9`（随包分发的默认配置，键同步改名；`target_ip` 等其余值不动）
- Modify: `app.py`（m1 行控件、`on_browse_bvh_folder` → `on_browse_bvh_archive`、`on_merge_bvh` 校验、`_load_config_into_ui` / `_persist_config` 键名、import）
- Test: `tests/test_bvh_ui.py`
- 已核实 `tests/test_app_poll.py` 无 `bvh_folder_entry` 引用，无需改动。

**Interfaces:**
- Consumes: Task 2 的 `BvhMerger.merge(archive, bvh_path, on_done)`；Task 1 的 `is_supported_archive`。
- Produces: UI 控件 `self.bvh_archive_entry`（CTkEntry）；处理器 `on_browse_bvh_archive`；配置键 `bvh_archive`（str）。

- [ ] **Step 1: Rewrite the failing UI tests**

`tests/test_bvh_ui.py` 全文替换为：

```python
"""BVH融合 UI wiring: entries restored from config, button gating, validation."""
import app as appmod


def _fresh_app():
    a = appmod.App()
    return a


def test_bvh_entries_restored_from_config(monkeypatch):
    a = _fresh_app()
    try:
        monkeypatch.setattr(appmod, "load_config", lambda: {
            "target_ip": "1.2.3.4", "port": 22, "username": "robot",
            "password": "x", "run_command": "ls",
            "bvh_archive": "D:/data-abc.tar.gz", "bvh_file": "D:/take.bvh",
            "last_bvh_dir": "D:/data", "local_ip": "",
        })
        a._load_config_into_ui()
        assert a.bvh_archive_entry.get() == "D:/data-abc.tar.gz"
        assert a.bvh_file_entry.get() == "D:/take.bvh"
        assert a._last_bvh_dir == "D:/data"
    finally:
        a.destroy()


def test_persist_config_includes_bvh_keys(monkeypatch):
    a = _fresh_app()
    try:
        a.bvh_archive_entry.delete(0, "end"); a.bvh_archive_entry.insert(0, "D:/data-abc.tar.gz")
        a.bvh_file_entry.delete(0, "end"); a.bvh_file_entry.insert(0, "D:/take.bvh")
        a._last_bvh_dir = "D:/data"
        saved = {}
        monkeypatch.setattr(appmod, "save_config", lambda cfg: saved.update(cfg))
        a._persist_config()
        assert saved["bvh_archive"] == "D:/data-abc.tar.gz"
        assert saved["bvh_file"] == "D:/take.bvh"
        assert saved["last_bvh_dir"] == "D:/data"
    finally:
        a.destroy()


def test_merge_button_disabled_while_merging():
    a = _fresh_app()
    try:
        assert a.merge_btn.cget("state") == "normal"
        a._merging = True
        a._refresh_controls()
        assert a.merge_btn.cget("state") == "disabled"
        a._merging = False
        a._refresh_controls()
        assert a.merge_btn.cget("state") == "normal"
    finally:
        a.destroy()


def test_on_merge_bvh_requires_both_paths_and_stays_idle():
    a = _fresh_app()
    try:
        # clear entries: this machine's config.json may carry real saved paths
        a.bvh_archive_entry.delete(0, "end")
        a.bvh_file_entry.delete(0, "end")
        a.on_merge_bvh()          # both entries now empty
        a._poll()                 # drain scheduled log callback
        assert a._merging is False
        assert "请先选择压缩包" in a.log_view.get("1.0", "end")
    finally:
        a.destroy()


def test_on_merge_bvh_rejects_missing_archive_and_wrong_suffix(tmp_path):
    a = _fresh_app()
    try:
        a.bvh_archive_entry.delete(0, "end")
        a.bvh_archive_entry.insert(0, str(tmp_path / "missing.tar.gz"))
        a.on_merge_bvh(); a._poll()
        assert "压缩包不存在" in a.log_view.get("1.0", "end")

        zip_like = tmp_path / "data.zip"; zip_like.write_bytes(b"PK")
        a.bvh_archive_entry.delete(0, "end")
        a.bvh_archive_entry.insert(0, str(zip_like))
        a.on_merge_bvh(); a._poll()
        assert "仅支持 tar.gz/tgz" in a.log_view.get("1.0", "end")
        assert a._merging is False   # never started
    finally:
        a.destroy()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bvh_ui.py -v`
Expected: FAIL with `AttributeError: 'App' object has no attribute 'bvh_archive_entry'`

- [ ] **Step 3: Implement config key rename and UI rewiring**

(a) `config_store.py` DEFAULTS 中 `"bvh_folder": "",` → `"bvh_archive": "",`

(b) `default_config.json` 中 `"bvh_folder": "",` → `"bvh_archive": "",`（其余键值原样保留）

(c) `app.py`:

import 行（原 `from core.bvh_merger import BvhMerger`）改为：

```python
from core.bvh_merger import BvhMerger, is_supported_archive
```

`_build_ui` 的 m1 行（原「文件夹:」三行）改为：

```python
        m1 = ctk.CTkFrame(mergef, fg_color="transparent"); m1.pack(fill="x", **pad)
        ctk.CTkLabel(m1, text="压缩包:").pack(side="left")
        self.bvh_archive_entry = ctk.CTkEntry(m1, width=360); self.bvh_archive_entry.pack(side="left", padx=8)
        ctk.CTkButton(m1, text="浏览", width=70, command=self.on_browse_bvh_archive).pack(side="left")
```

`_load_config_into_ui` 中（原 `self.bvh_folder_entry...` 两行）改为：

```python
        self.bvh_archive_entry.delete(0, "end")
        self.bvh_archive_entry.insert(0, cfg.get("bvh_archive", ""))
```

`_persist_config` 中 `"bvh_folder": self.bvh_folder_entry.get(),` 改为：

```python
                "bvh_archive": self.bvh_archive_entry.get(),
```

`on_browse_bvh_folder` 整体替换为：

```python
    def on_browse_bvh_archive(self):
        path = filedialog.askopenfilename(
            initialdir=self._last_bvh_dir or None,
            filetypes=[("压缩包", "*.tar.gz *.tgz")],
        )
        if path:
            self.bvh_archive_entry.delete(0, "end")
            self.bvh_archive_entry.insert(0, path)
            self._last_bvh_dir = os.path.dirname(path)
```

`on_merge_bvh` 整体替换为：

```python
    def on_merge_bvh(self):
        archive = self.bvh_archive_entry.get().strip()
        bvh = self.bvh_file_entry.get().strip()
        if not archive:
            self._log("[BVH融合] 请先选择压缩包(tar.gz)\n"); return
        if not os.path.isfile(archive):
            self._log(f"[BVH融合] 压缩包不存在: {archive}\n"); return
        if not is_supported_archive(archive):
            self._log(f"[BVH融合] 仅支持 tar.gz/tgz 压缩包: {archive}\n"); return
        if not bvh:
            self._log("[BVH融合] 请先选择 BVH 文件\n"); return
        self._merging = True
        self._refresh_controls()

        def done(ok, error):
            self._merging = False
            self._refresh_controls()

        self.merger.merge(archive, bvh, done)
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS（含 robot_controller / ssh_session / app_poll / bvh_merger / bvh_ui）

- [ ] **Step 5: Commit**

```bash
git add config_store.py default_config.json app.py tests/test_bvh_ui.py
git commit -m "feat: BVH融合 UI selects a tar.gz archive; config key bvh_archive"
```

---

## Self-Review 结论

- **Spec coverage:** UI 过滤/校验文案（Task 3）、解压+filter="data"（Task 2）、单顶层目录定位（Task 1+2）、原名拷入（Task 2）、产物回拷+覆盖（Task 2）、临时清理与失败不留产物（Task 2）、配置键改名不迁移（Task 3）、测试清单（Task 1-3）——全部覆盖。spec 提及 test_app_poll.py 可能需改名，已核实无引用，计划中注明。
- **Type consistency:** `is_supported_archive`/`merge_dir_in_extracted`/`bvh_archive_entry`/`bvh_archive`/`on_browse_bvh_archive` 在各任务间签名一致；`merge(archive, bvh_path, on_done)` 与 app.py 调用一致。
- **Placeholder scan:** 无 TBD/TODO；每步含完整代码与命令。
