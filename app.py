"""Main window: layout, worker-thread marshalling, button handlers."""
import os
from pathlib import Path
import queue
import threading
import time

import customtkinter as ctk
from tkinter import filedialog

from config_store import ensure_default_config_file, load_config, restore_defaults, save_config
from core.net_info import list_local_ipv4
from core.ssh_session import SSHSession
from core.robot_controller import RobotController, binary_path_from_command
from core.program_runner import ProgramRunner
from ui.log_view import LogView

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Sniffer")
        self.geometry("760x680")
        self.minsize(660, 600)

        self._queue: "queue.Queue" = queue.Queue()
        self._last_dir = ""
        self._connected = False
        self._mocap_dir = ""
        self._copying_data = False

        self.session = SSHSession()
        self.controller = RobotController(
            self.session,
            schedule=self._schedule,
            log=self._log,
            sudo_password=lambda: self.pw_entry.get(),
        )
        self.runner = ProgramRunner(
            self.session,
            on_output=self._log,
            on_ended=lambda: self._schedule(self._on_run_ended),
            sudo_password=lambda: self.pw_entry.get(),
            on_mocap_dir=lambda path: self._schedule(
                lambda path=path: self._set_mocap_dir(path)
            ),
        )

        self._build_ui()
        ensure_default_config_file()
        self._load_config_into_ui()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- layout ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        conn = ctk.CTkFrame(self)
        conn.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(conn, text="连接设置", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))

        r1 = ctk.CTkFrame(conn, fg_color="transparent"); r1.pack(fill="x", **pad)
        ctk.CTkLabel(r1, text="本地IP:").pack(side="left")
        self.local_ip_var = ctk.StringVar()
        self.local_ip_box = ctk.CTkOptionMenu(r1, variable=self.local_ip_var, values=[], width=180)
        self.local_ip_box.pack(side="left", padx=8)
        ctk.CTkButton(r1, text="↻", width=36, command=self.on_refresh_local_ips,
                      font=ctk.CTkFont(size=16)).pack(side="left")
        ctk.CTkLabel(r1, text="端口:").pack(side="left", padx=(16, 0))
        self.port_entry = ctk.CTkEntry(r1, width=70); self.port_entry.insert(0, "22"); self.port_entry.pack(side="left", padx=8)

        r2 = ctk.CTkFrame(conn, fg_color="transparent"); r2.pack(fill="x", **pad)
        ctk.CTkLabel(r2, text="目标IP:").pack(side="left")
        self.target_entry = ctk.CTkEntry(r2, width=200); self.target_entry.pack(side="left", padx=8)
        ctk.CTkLabel(r2, text="用户名:").pack(side="left", padx=(16, 0))
        self.user_entry = ctk.CTkEntry(r2, width=120); self.user_entry.pack(side="left", padx=8)

        r3 = ctk.CTkFrame(conn, fg_color="transparent"); r3.pack(fill="x", **pad)
        ctk.CTkLabel(r3, text="密码:").pack(side="left")
        self.pw_entry = ctk.CTkEntry(r3, width=200, show="*"); self.pw_entry.pack(side="left", padx=8)
        self.pw_show_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(r3, text="显示", variable=self.pw_show_var, command=self._toggle_pw).pack(side="left", padx=8)
        self.connect_btn = ctk.CTkButton(r3, text="连接", width=100, command=self.on_connect)
        self.connect_btn.pack(side="left", padx=(16, 0))
        self.status_label = ctk.CTkLabel(r3, text="● 未连接", text_color="#e07b7b")
        self.status_label.pack(side="left", padx=12)

        r4 = ctk.CTkFrame(conn, fg_color="transparent"); r4.pack(fill="x", **pad)
        ctk.CTkButton(r4, text="恢复默认配置", width=120, command=self.on_restore_defaults).pack(side="right")

        deploy = ctk.CTkFrame(self); deploy.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(deploy, text="程序部署", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        d1 = ctk.CTkFrame(deploy, fg_color="transparent"); d1.pack(fill="x", **pad)
        self.archive_entry = ctk.CTkEntry(d1, width=360); self.archive_entry.pack(side="left")
        ctk.CTkButton(d1, text="浏览", width=70, command=self.on_browse).pack(side="left", padx=8)
        self.upload_btn = ctk.CTkButton(d1, text="上传并解压", width=120, command=self.on_upload)
        self.upload_btn.pack(side="left", padx=8)
        chk = ctk.CTkFrame(deploy, fg_color="transparent"); chk.pack(fill="x", padx=8, pady=(2, 6))
        self.check_label = ctk.CTkLabel(chk, text="程序检查 ~/ats/sniffer: ❓ 未知")
        self.check_label.pack(side="left")
        ctk.CTkButton(chk, text="↻", width=36, command=self.on_refresh_check,
                      font=ctk.CTkFont(size=16)).pack(side="left", padx=8)

        runf = ctk.CTkFrame(self); runf.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(runf, text="运行", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        rf_cmd = ctk.CTkFrame(runf, fg_color="transparent"); rf_cmd.pack(fill="x", **pad)
        ctk.CTkLabel(rf_cmd, text="运行命令:").pack(side="left")
        self.run_cmd_entry = ctk.CTkEntry(rf_cmd)
        self.run_cmd_entry.pack(side="left", padx=8, fill="x", expand=True)
        rf1 = ctk.CTkFrame(runf, fg_color="transparent"); rf1.pack(fill="x", **pad)
        self.run_btn = ctk.CTkButton(rf1, text="运行", width=120, command=self.on_run_toggle)
        self.run_btn.pack(side="left")
        self.delete_btn = ctk.CTkButton(rf1, text="删除 ~/ats/sniffer", width=180,
                                        fg_color="#a33", hover_color="#922", command=self.on_delete)
        self.delete_btn.pack(side="left", padx=12)
        self.mocap_dir_label = ctk.CTkLabel(
            runf, text="Mocap目录: 等待程序输出", anchor="w"
        )
        self.mocap_dir_label.pack(fill="x", padx=8, pady=(0, 6))

        copyf = ctk.CTkFrame(self); copyf.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(copyf, text="数据拷贝删除", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        copy_row = ctk.CTkFrame(copyf, fg_color="transparent"); copy_row.pack(fill="x", **pad)
        self.copy_btn = ctk.CTkButton(copy_row, text="拷贝删除", width=120,
                                      command=self.on_copy_data)
        self.copy_btn.pack(side="left")
        self.copy_progress = ctk.CTkProgressBar(copy_row, mode="determinate")
        self.copy_progress.pack(side="left", padx=12, fill="x", expand=True)
        self.copy_progress.set(0)
        self.copy_progress_label = ctk.CTkLabel(copy_row, text="0%", width=150)
        self.copy_progress_label.pack(side="left")

        ctk.CTkLabel(self, text="日志", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=16, pady=(8, 0))
        self.log_view = LogView(self, height=240)
        self.log_view.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        self._refresh_controls()

    # ---------------- threading bridge ----------------
    def _schedule(self, fn):
        self._queue.put(fn)

    def _poll(self):
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                # Isolate each callback so one failure can never kill the poll loop
                # (which would freeze the whole UI). Surface it in the log instead.
                try:
                    self.log_view.append(f"[内部错误] {e}\n")
                except Exception:
                    pass
        self.after(100, self._poll)

    def _log(self, text: str):
        self._schedule(lambda: self.log_view.append(text))

    # ---------------- config ----------------
    def _load_config_into_ui(self):
        cfg = load_config()
        for entry in (self.target_entry, self.port_entry, self.user_entry,
                      self.pw_entry, self.run_cmd_entry):
            entry.delete(0, "end")
        self.target_entry.insert(0, cfg.get("target_ip", "192.168.1.111"))
        self.port_entry.insert(0, str(cfg.get("port", 22)))
        self.user_entry.insert(0, cfg.get("username", "robot"))
        self.pw_entry.insert(0, cfg.get("password", "MangoTango"))
        self._last_dir = cfg.get("last_archive_dir", "")
        self.run_cmd_entry.insert(0, cfg.get("run_command", "cd ~/ats && sudo ./sniffer --bin"))
        self._refresh_local_ips(initial=cfg.get("local_ip", ""))

    def _refresh_local_ips(self, initial=""):
        ips = list_local_ipv4()
        if not ips:
            ips = [""]
        self.local_ip_box.configure(values=ips)
        if initial in ips:
            chosen = initial
        else:
            chosen = self._preferred_local_ip(ips)
        self.local_ip_var.set(chosen)

    def _preferred_local_ip(self, ips):
        # Prefer an adapter in the same /24 as the target (e.g. 192.168.1.x
        # for a 192.168.1.x robot); fall back to the first detected IP.
        octets = self.target_entry.get().strip().split(".")
        if len(octets) == 4:
            prefix = ".".join(octets[:3]) + "."
            for ip in ips:
                if ip.startswith(prefix):
                    return ip
        return ips[0] if ips else ""

    def on_refresh_local_ips(self):
        # keep the current selection if it is still present after re-scan
        self._refresh_local_ips(initial=self.local_ip_var.get())
        self._log(f"[本地IP] 已刷新: {', '.join(list_local_ipv4() or ['未检测到'])}\n")

    def on_refresh_check(self):
        if not self.session.connected:
            self._log("[检查] 请先连接目标\n"); return

        def work():
            present = self.controller.program_present_sync()
            self._log(f"[检查] ~/ats/sniffer {'已存在' if present else '不存在'}\n")
            self._schedule(lambda: self._set_check(present))

        threading.Thread(target=work, daemon=True).start()

    def on_restore_defaults(self):
        # Copy default_config.json -> config.json, then reload fields.
        restore_defaults()
        # config changed -> drop any connection that is now to a stale target
        try:
            if self.runner.is_running:
                self.runner.stop()
        except Exception:
            pass
        try:
            self.session.close()
        except Exception:
            pass
        self._connected = False
        self._set_status(False)
        self._set_check(None)
        self._load_config_into_ui()
        self._refresh_controls()
        self._log("[配置] 已恢复默认配置，请重新连接\n")

    def _persist_config(self):
        try:
            save_config({
                "local_ip": self.local_ip_var.get(),
                "target_ip": self.target_entry.get(),
                "port": int(self.port_entry.get() or 22),
                "username": self.user_entry.get(),
                "password": self.pw_entry.get(),
                "last_archive_dir": self._last_dir,
                "run_command": self.run_cmd_entry.get(),
            })
        except Exception as e:
            self._log(f"[保存配置失败] {e}\n")

    # ---------------- helpers ----------------
    def _toggle_pw(self):
        self.pw_entry.configure(show="" if self.pw_show_var.get() else "*")

    def _set_status(self, connected: bool):
        self._connected = connected
        self.status_label.configure(
            text="● 已连接" if connected else "● 未连接",
            text_color="#7be08b" if connected else "#e07b7b",
        )

    def _set_check(self, present):
        if present is True:
            self.check_label.configure(text="程序检查 ~/ats/sniffer: ✅ 已存在", text_color="#7be08b")
        elif present is False:
            self.check_label.configure(text="程序检查 ~/ats/sniffer: ❌ 不存在", text_color="#e07b7b")
        else:
            self.check_label.configure(text="程序检查 ~/ats/sniffer: ❓ 未知", text_color="#cccccc")

    def _set_mocap_dir(self, path=""):
        self._mocap_dir = path
        text = f"Mocap目录: {path}" if path else "Mocap目录: 等待程序输出"
        self.mocap_dir_label.configure(text=text)
        self._refresh_controls()

    def _set_copy_progress(self, transferred, total):
        if total > 0:
            fraction = min(1.0, max(0.0, transferred / total))
            self.copy_progress.set(fraction)
            self.copy_progress_label.configure(
                text=f"{fraction:.0%} ({transferred} / {total} 字节)"
            )
        else:
            self.copy_progress.set(0)
            self.copy_progress_label.configure(text=f"{transferred} 字节")

    def _refresh_controls(self):
        running = self.runner.is_running
        self.connect_btn.configure(state="disabled" if running else "normal")
        ok = self._connected and not running
        self.upload_btn.configure(state="normal" if ok else "disabled")
        self.delete_btn.configure(state="normal" if ok else "disabled")
        self.run_btn.configure(state="normal" if self._connected else "disabled",
                               text="停止" if running else "运行")
        can_copy = self._connected and bool(self._mocap_dir) and not self._copying_data
        self.copy_btn.configure(state="normal" if can_copy else "disabled")

    # ---------------- handlers ----------------
    def on_browse(self):
        path = filedialog.askopenfilename(
            initialdir=self._last_dir or None,
            filetypes=[("压缩包", "*.tar.gz *.tgz *.tar *.zip"), ("所有文件", "*.*")],
        )
        if path:
            self.archive_entry.delete(0, "end")
            self.archive_entry.insert(0, path)
            self._last_dir = os.path.dirname(path)

    def on_connect(self):
        host = self.target_entry.get().strip()
        if not host:
            self._log("[连接] 请填写目标IP\n"); return
        self.connect_btn.configure(state="disabled")
        self._log(f"[连接中] {host} ...\n")

        def done(connected, present, error):
            self._set_status(connected)
            self._set_check(present)
            if connected:
                self._log("[连接成功]\n")
            self._refresh_controls()

        self.controller.connect_and_check(
            host, self.port_entry.get(), self.user_entry.get(), self.pw_entry.get(), done
        )

    def on_upload(self):
        path = self.archive_entry.get().strip()
        if not path or not os.path.isfile(path):
            self._log("[上传] 请先选择有效的压缩包文件\n"); return
        self.upload_btn.configure(state="disabled")

        def done(ok, error, present=None):
            self._set_check(present)
            self._refresh_controls()

        self.controller.upload_and_decompress(path, done)

    def on_delete(self):
        self.delete_btn.configure(state="disabled")

        def done(ok, error, present=None):
            self._set_check(present)
            self._refresh_controls()

        self.controller.delete_program(done)

    def on_copy_data(self):
        if not self.session.connected:
            self._log("[数据拷贝] 请先连接目标\n"); return
        if not self._mocap_dir:
            self._log("[数据拷贝] 尚未获取 mocap 目录\n"); return
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
            self._mocap_dir, str(Path.cwd()), done,
            on_progress=self._set_copy_progress,
        )

    def on_run_toggle(self):
        if self.runner.is_running:
            self.runner.stop()
            self._log("[停止] 已发送 Ctrl+C\n")
            return
        if not self.session.connected:
            self._log("[运行] 请先连接目标\n"); return
        command = self.run_cmd_entry.get().strip()
        if not command:
            self._log("[运行] 运行命令为空\n"); return
        self.run_btn.configure(state="disabled")
        self._set_mocap_dir()

        def work():
            try:
                binary = binary_path_from_command(command)
                if binary and not self.controller.program_present_sync(binary):
                    self._log(f"[运行失败] {binary} 不存在，请先上传并解压部署\n")
                    self._schedule(self._refresh_controls)
                    return
                self.runner.start(command)
            except Exception as e:
                self._log(f"[运行失败] {e}\n")
                self._schedule(self._refresh_controls)
                return
            # Button -> 停止 immediately now that the program is launched.
            self._schedule(self._refresh_controls)
            # Then confirm it actually stays up before logging success;
            # a broken binary exits almost immediately and reverts the button.
            time.sleep(1.2)
            if self.runner.is_running:
                self._log(f"[运行成功] {command} 已启动\n")
            else:
                self._log("[运行失败] 程序启动后立即退出，请查看上方输出\n")
            self._schedule(self._refresh_controls)

        threading.Thread(target=work, daemon=True).start()

    def _on_run_ended(self):
        self._log("[运行结束]\n")
        self._refresh_controls()

    def _on_close(self):
        try:
            if self.runner.is_running:
                self.runner.stop()
        except Exception:
            pass
        self._persist_config()
        try:
            self.controller.close()
        except Exception:
            pass
        self.destroy()
