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
