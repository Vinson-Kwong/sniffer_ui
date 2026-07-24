"""Main window: layout, worker-thread marshalling, button handlers."""
import os
import queue
import threading

import customtkinter as ctk
from tkinter import filedialog

from config_store import load_config, save_config
from core.net_info import list_local_ipv4
from core.ssh_session import SSHSession
from core.robot_controller import RobotController
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
        )

        self._build_ui()
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

        deploy = ctk.CTkFrame(self); deploy.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(deploy, text="部署", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        d1 = ctk.CTkFrame(deploy, fg_color="transparent"); d1.pack(fill="x", **pad)
        self.archive_entry = ctk.CTkEntry(d1, width=360); self.archive_entry.pack(side="left")
        ctk.CTkButton(d1, text="浏览", width=70, command=self.on_browse).pack(side="left", padx=8)
        self.upload_btn = ctk.CTkButton(d1, text="上传并解压", width=120, command=self.on_upload)
        self.upload_btn.pack(side="left", padx=8)
        self.check_label = ctk.CTkLabel(deploy, text="程序检查 ~/ats/sniffer: ❓ 未知")
        self.check_label.pack(anchor="w", padx=8, pady=(2, 6))

        runf = ctk.CTkFrame(self); runf.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(runf, text="运行", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        rf1 = ctk.CTkFrame(runf, fg_color="transparent"); rf1.pack(fill="x", **pad)
        self.run_btn = ctk.CTkButton(rf1, text="运行", width=120, command=self.on_run_toggle)
        self.run_btn.pack(side="left")
        self.delete_btn = ctk.CTkButton(rf1, text="删除 ~/ats/sniffer", width=180,
                                        fg_color="#a33", hover_color="#922", command=self.on_delete)
        self.delete_btn.pack(side="left", padx=12)

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
        self.target_entry.insert(0, cfg.get("target_ip", "192.168.1.111"))
        self.port_entry.delete(0, "end"); self.port_entry.insert(0, str(cfg.get("port", 22)))
        self.user_entry.insert(0, cfg.get("username", "robot"))
        self.pw_entry.insert(0, cfg.get("password", "MangoTango"))
        self._last_dir = cfg.get("last_archive_dir", "")
        self._refresh_local_ips(initial=cfg.get("local_ip", ""))

    def _refresh_local_ips(self, initial=""):
        ips = list_local_ipv4()
        if not ips:
            ips = [""]
        self.local_ip_box.configure(values=ips)
        chosen = initial if initial in ips else (ips[0] if ips else "")
        self.local_ip_var.set(chosen)

    def _persist_config(self):
        try:
            save_config({
                "local_ip": self.local_ip_var.get(),
                "target_ip": self.target_entry.get(),
                "port": int(self.port_entry.get() or 22),
                "username": self.user_entry.get(),
                "password": self.pw_entry.get(),
                "last_archive_dir": self._last_dir,
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

    def _refresh_controls(self):
        running = self.runner.is_running
        self.connect_btn.configure(state="disabled" if running else "normal")
        ok = self._connected and not running
        self.upload_btn.configure(state="normal" if ok else "disabled")
        self.delete_btn.configure(state="normal" if ok else "disabled")
        self.run_btn.configure(state="normal" if self._connected else "disabled",
                               text="停止" if running else "运行")

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

    def on_run_toggle(self):
        if self.runner.is_running:
            self.runner.stop()
            self._log("[停止] 已发送 Ctrl+C\n")
            return
        if not self.session.connected:
            self._log("[运行] 请先连接目标\n"); return
        self.run_btn.configure(state="disabled")

        def work():
            try:
                self.runner.start()
                self._log("[运行成功] sudo ~/ats/sniffer --bin 已启动\n")
                self._schedule(self._refresh_controls)
            except Exception as e:
                self._log(f"[运行失败] {e}\n")
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
