import socket

import core.net_info as net_info


def test_excludes_loopback_and_dedupes(monkeypatch):
    def fake_byname_ex(host):
        return (host, [], ["192.168.1.10", "192.168.1.10", "10.0.0.7"])

    def fake_gethostname():
        return "myhost"

    class FakeSock:
        def connect(self, *a, **k):
            pass

        def getsockname(self):
            return ("192.168.1.10", 0)

        def close(self):
            pass

    monkeypatch.setattr(socket, "gethostbyname_ex", fake_byname_ex)
    monkeypatch.setattr(socket, "gethostname", fake_gethostname)
    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())

    addrs = net_info.list_local_ipv4()
    assert addrs[0] == "192.168.1.10"        # primary outbound IP first
    assert "10.0.0.7" in addrs
    assert "127.0.0.1" not in addrs
    assert len(addrs) == len(set(addrs))     # de-duplicated


def test_returns_empty_when_host_resolution_fails(monkeypatch):
    def raise_gaierror(*a, **k):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "gethostbyname_ex", raise_gaierror)

    class FakeSock:
        def connect(self, *a, **k):
            raise OSError("no route")

        def getsockname(self):
            return ("127.0.0.1", 0)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
    assert net_info.list_local_ipv4() == []
