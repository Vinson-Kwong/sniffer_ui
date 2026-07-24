import socket
from types import SimpleNamespace

import core.net_info as net_info


def _fake_psutil(adapters):
    """adapters: {name: (isup, [ipv4,...])}"""
    stats = {name: SimpleNamespace(isup=up) for name, (up, _) in adapters.items()}
    addrs = {
        name: [SimpleNamespace(family=socket.AF_INET, address=ip) for ip in ips]
        for name, (_, ips) in adapters.items()
    }
    return SimpleNamespace(net_if_stats=lambda: stats, net_if_addrs=lambda: addrs)


def test_psutil_path_skips_down_loopback_and_linklocal(monkeypatch):
    monkeypatch.setattr(net_info, "psutil", _fake_psutil({
        "eth": (True, ["192.168.1.20", "192.168.1.20", "169.254.1.1"]),  # dup + link-local
        "wifi": (False, ["192.168.1.50"]),   # disabled -> excluded
        "lo": (True, ["127.0.0.1"]),         # loopback -> excluded
    }))
    assert net_info.list_local_ipv4() == ["192.168.1.20"]


def test_psutil_path_lists_multiple_up_adapters(monkeypatch):
    monkeypatch.setattr(net_info, "psutil", _fake_psutil({
        "eth": (True, ["192.168.1.20"]),
        "vnic": (True, ["172.24.48.1"]),
    }))
    assert set(net_info.list_local_ipv4()) == {"192.168.1.20", "172.24.48.1"}


def test_fallback_udp_probe_when_psutil_missing(monkeypatch):
    monkeypatch.setattr(net_info, "psutil", None)

    class FakeSock:
        def connect(self, *a, **k):
            pass

        def getsockname(self):
            return ("10.0.0.9", 0)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
    assert net_info.list_local_ipv4() == ["10.0.0.9"]


def test_fallback_empty_when_no_route(monkeypatch):
    monkeypatch.setattr(net_info, "psutil", None)

    class FakeSock:
        def connect(self, *a, **k):
            raise OSError("no route")

        def getsockname(self):
            return ("127.0.0.1", 0)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
    assert net_info.list_local_ipv4() == []
