"""Enumerate this machine's non-loopback IPv4 addresses (stdlib only)."""
import socket


def list_local_ipv4() -> list[str]:
    addrs: list[str] = []
    seen: set[str] = set()

    def _add(ip: str) -> None:
        if ip and not ip.startswith("127.") and ip not in seen:
            seen.add(ip)
            addrs.append(ip)

    # 1) UDP "fake connect" reveals the primary outbound interface IP.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            _add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass

    # 2) gethostbyname_ex may surface additional interface IPs.
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            _add(ip)
    except socket.gaierror:
        pass

    return addrs
