"""UI poll-loop robustness: one raising callback must not freeze the queue."""
import app as appmod


def _boom():
    raise RuntimeError("boom")


def test_poll_survives_a_raising_callback_and_keeps_draining():
    a = appmod.App()
    try:
        a.update_idletasks()
        seen = []
        a._schedule(_boom)                       # this callback raises
        a._schedule(lambda: seen.append("after"))  # this must still run
        a._poll()                                # drains the queue once
        assert seen == ["after"], "later callbacks dropped after a raising one"
    finally:
        a.destroy()


def test_mocap_dir_label_can_be_updated_and_reset():
    a = appmod.App()
    try:
        a._connected = True
        a._set_mocap_dir("/tmp/mocap/session-1")
        assert a.mocap_dir_label.cget("text") == "Mocap目录: /tmp/mocap/session-1"
        assert a.copy_btn.cget("state") == "normal"
        a._set_mocap_dir()
        assert a.mocap_dir_label.cget("text") == "Mocap目录: 等待程序输出"
        assert a.copy_btn.cget("state") == "disabled"
    finally:
        a.destroy()


def test_copy_progress_displays_fraction_and_handles_unknown_total():
    a = appmod.App()
    try:
        a._set_copy_progress(25, 100)
        assert a.copy_progress.get() == 0.25
        assert a.copy_progress_label.cget("text") == "25% (25 / 100 字节)"

        a._set_copy_progress(150, 100)
        assert a.copy_progress.get() == 1.0

        a._set_copy_progress(42, 0)
        assert a.copy_progress.get() == 0.0
        assert a.copy_progress_label.cget("text") == "42 字节"
    finally:
        a.destroy()
