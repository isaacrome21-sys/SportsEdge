"""t258 network jail for child Python processes spawned under the DK no-live-request guard
(tests/test_dk_api_no_live_requests_in_ci_20261023.py puts this directory first on
PYTHONPATH). Any connect/resolve to a non-loopback address raises; loopback still works."""
import ipaddress
import socket

_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def _local(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if host is None or host == "":
        return True
    if not isinstance(host, str):
        return False
    if host.lower() in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _refuse(where, host):
    raise OSError(f"LIVE_NETWORK_BLOCKED:{where}:{host}")


_gai, _cc = socket.getaddrinfo, socket.create_connection
_connect, _connect_ex, _sendto = socket.socket.connect, socket.socket.connect_ex, socket.socket.sendto


def getaddrinfo(host, *a, **k):
    if not _local(host):
        _refuse("getaddrinfo", host)
    return _gai(host, *a, **k)


def create_connection(address, *a, **k):
    if not _local(address[0]):
        _refuse("create_connection", address[0])
    return _cc(address, *a, **k)


def _inet(sock, address):
    return sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple)


def connect(self, address):
    if _inet(self, address) and not _local(address[0]):
        _refuse("socket.connect", address[0])
    return _connect(self, address)


def connect_ex(self, address):
    if _inet(self, address) and not _local(address[0]):
        _refuse("socket.connect_ex", address[0])
    return _connect_ex(self, address)


def sendto(self, data, *args):
    address = args[-1]
    if _inet(self, address) and not _local(address[0]):
        _refuse("socket.sendto", address[0])
    return _sendto(self, data, *args)


socket.getaddrinfo = getaddrinfo
socket.create_connection = create_connection
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
socket.socket.sendto = sendto
