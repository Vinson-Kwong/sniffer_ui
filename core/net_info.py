"""Enumerate this machine's currently-active, non-loopback IPv4 addresses."""
import socket

try:
    import psutil
except ImportError:
    psutil = None


def _useful(ip: str) -> bool:
    return bool(ip) and not ip.startswith("127.") and not ip.startswith("169.254.")


def list_local_ipv4() -> list[str]:
    """IPv4 addresses of UP adapters, in real time.

    Uses psutil so a disabled adapter (e.g. WiFi turned off) is NOT listed --
    unlike socket.gethostbyname, which returns stale cached entries on Windows.
    Falls back to a UDP probe of the primary outbound IP if psutil is missing."""
    addrs: list[str] = []
    seen: set[str] = set()

    def _add(ip: str) -> None:
        if _useful(ip) and ip not in seen:
            seen.add(ip)
            addrs.append(ip)

    if psutil is not None:
        try:
            stats = psutil.net_if_stats()
            for name, snics in psutil.net_if_addrs().items():
                st = stats.get(name)
                if st is not None and not st.isup:
                    continue  # adapter disabled / down -> skip
                for snic in snics:
                    if snic.family == socket.AF_INET:
                        _add(snic.address)
            if addrs:
                return addrs
        except Exception:
            pass  # fall through to stdlib probe

    # Fallback: primary outbound IP (real time, single address only)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            _add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass

    return addrs
