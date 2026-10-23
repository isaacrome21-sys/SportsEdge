"""Auto-triggered CI jobs that import DraftKings-API modules must not reach a DraftKings
host. Grok ruling 2026-10-23 (t234u): these jobs only test against fixtures/mocks, so they
keep their triggers; this guard runs exactly the DK-importing test modules they run with
every socket, urllib and requests entry point patched to refuse any *draftkings* host.
"""
import importlib
import io
import os
import re
import shutil
import subprocess
import socket
import sys
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# workflow -> DK-importing test modules it runs on push/pull_request/workflow_run/issues
GUARDED = {
    "market-maker-radar.yml": ["tests.test_capture_nfl_market_maker_radar"],
    "collection-runtime-contract.yml": ["tests.test_archive_mlb_prop_odds"],
    "mlb-additional-odds-contract.yml": ["tests.test_mlb_quote_source_coverage"],
    "mlb-additional-pit-archive.yml": ["tests.test_mlb_quote_source_coverage"],
    "football-nfl-promotion-evidence.yml": [
        "tests.test_nfl_2026_direct_capture_wiring",
        "tests.test_nfl_card_game_info", "tests.test_nfl_direct_capture_source",
        "tests.test_nfl_direct_dk_preflight"],
    "nfl-v2-nested-diagnostic.yml": [
        "tests.test_nfl_2026_direct_capture_wiring", "tests.test_nfl_card_game_info",
        "tests.test_nfl_direct_capture_source", "tests.test_nfl_direct_dk_preflight"],
    "nfl-v2h-first-readout.yml": [
        "tests.test_nfl_2026_direct_capture_wiring", "tests.test_nfl_card_game_info",
        "tests.test_nfl_direct_capture_source", "tests.test_nfl_direct_dk_preflight"],
    "nfl-v2i-first-readout.yml": [
        "tests.test_nfl_2026_direct_capture_wiring", "tests.test_nfl_card_game_info",
        "tests.test_nfl_direct_capture_source", "tests.test_nfl_direct_dk_preflight"],
    "nfl-v2j-first-readout.yml": [
        "tests.test_nfl_2026_direct_capture_wiring", "tests.test_nfl_card_game_info",
        "tests.test_nfl_direct_capture_source", "tests.test_nfl_direct_dk_preflight"],
}
# nfl-lines-issue.yml runs scripts/render_nfl_myspari_card.py, which reaches the DK dfs
# modules only through `sportsedge.dfs` package imports (ESPN public_json helper).
# football-nfl-promotion-evidence runs `unittest discover -p 'test_football*.py'`, which
# imports tests/test_football_all_props_finish.py (pytest-style; unittest collects 0 tests).
IMPORT_ONLY_SCRIPTS = {"nfl-lines-issue.yml": ["scripts.render_nfl_myspari_card"],
                       "football-nfl-promotion-evidence.yml": ["tests.test_football_all_props_finish"]}
# collection-runtime-contract also runs `python -I scripts/archive_mlb_prop_odds.py --self-test`
SELF_TESTS = {"collection-runtime-contract.yml": [("scripts.archive_mlb_prop_odds", "_self_test")]}
MODULES = sorted({m for ms in GUARDED.values() for m in ms})
DK_HOSTS = ("sportsbook-nash.draftkings.com", "sportsbook.draftkings.com", "api.draftkings.com")


def _resolve_dk_ips():
    """Best effort: IPs the DK hosts resolve to now, so a hard-coded IP is refused too."""
    ips = set()
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(3)
    try:
        for h in DK_HOSTS:
            try:
                ips |= {ai[4][0] for ai in socket.getaddrinfo(h, 443)}
            except OSError:
                pass
    finally:
        socket.setdefaulttimeout(old)
    return frozenset(ips)


_DK_IPS = None


class DraftKingsBlocked(OSError):
    pass


def _is_dk(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if not isinstance(host, str):
        return False
    for _ in range(3):   # t258: api.%64raftkings.com (and double encoding) is still DK
        host = urllib.parse.unquote(host)
    return "draftkings" in host.lower() or host in (_DK_IPS or ())


# t258: the guard jails the WHOLE test process and its children, not just DK names.
JAIL_DIR = ROOT / "tests" / "net_jail"
DEAD_PROXY = "http://127.0.0.1:9"
_NET_BINARIES = {"curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "ssh", "scp",
                 "sftp", "rsync", "ftp", "openssl", "gnutls-cli", "aria2c", "httpie", "http"}
_UNSHARE = None


def _is_local(host) -> bool:
    import ipaddress
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if host is None or host == "":
        return True
    if not isinstance(host, str):
        return False
    if host.lower() in ("localhost", "localhost.localdomain", "ip6-localhost"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _unshare_prefix():
    """['unshare','-rn'] if an unprivileged empty network namespace works here, else None."""
    global _UNSHARE
    if os.environ.get("SPORTSEDGE_NET_JAIL_FORCE_FALLBACK") == "1":
        return None
    if _UNSHARE is None:
        _UNSHARE = []
        exe = shutil.which("unshare")
        if exe:
            try:
                if subprocess.run([exe, "-rn", "true"], capture_output=True, timeout=10).returncode == 0:
                    _UNSHARE = [exe, "-rn"]
            except (OSError, subprocess.SubprocessError):
                pass
    return _UNSHARE or None


_NET_BIN_DIGESTS = None


def _file_digest(path):
    import hashlib
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _is_net_binary_file(path) -> bool:
    """t259: a renamed copy of curl/wget/nc/... is still that binary (match by content)."""
    global _NET_BIN_DIGESTS
    if _NET_BIN_DIGESTS is None:
        found = {shutil.which(b) for b in _NET_BINARIES} - {None}
        _NET_BIN_DIGESTS = {os.path.realpath(p) for p in found} | {d for d in map(_file_digest, found) if d}
    if not path:
        return False
    path = os.fspath(path)
    if isinstance(path, bytes):
        path = path.decode("utf-8", "ignore")
    full = path if os.sep in path else (shutil.which(path) or path)
    if os.path.basename(os.path.realpath(full)) in _NET_BINARIES or os.path.realpath(full) in _NET_BIN_DIGESTS:
        return True
    return os.path.isfile(full) and _file_digest(full) in _NET_BIN_DIGESTS


def _fallback_net_cmd(args) -> bool:
    """Without a namespace: refuse any child that names a network binary or raw /dev/tcp,
    or shell text running a Python that ignores PYTHONPATH/site (-I/-E/-S)."""
    if isinstance(args, (bytes, str)):
        text = args.decode() if isinstance(args, bytes) else args
        toks = re.split(r"[\s;&|()`'\"<>]+", text)
    else:
        toks = [a.decode() if isinstance(a, bytes) else str(a) for a in args]
        text = " ".join(toks)
    names = {os.path.basename(t) for t in toks if t}
    if names & _NET_BINARIES or "/dev/tcp/" in text or "/dev/udp/" in text:
        return True
    if not isinstance(args, (bytes, str)) and toks and _is_net_binary_file(toks[0]):
        return True
    if isinstance(args, (bytes, str)):   # shell text cannot be rewritten: refuse -I/-E/-S
        return any(os.path.basename(t).startswith("python") for t in toks) and bool(
            {"-I", "-E", "-S"} & set(toks))
    return False


_JAIL_BOOT = ("import sys,runpy;runpy.run_path({jail!r}+'/sitecustomize.py',run_name='_sportsedge_net_jail');"
              "sys.argv={argv!r};")


def _jail_isolated_python(args):
    """Argv-list Python child with -I/-E/-S ignores PYTHONPATH/site and so the sitecustomize
    jail: rewrite it to load the jail first, keeping its flags. None -> refuse."""
    if isinstance(args, (bytes, str)) or not args:
        return args
    args = [a.decode() if isinstance(a, bytes) else str(a) for a in args]
    if not os.path.basename(args[0]).startswith("python"):
        return args
    i, flags = 1, []
    while i < len(args) and args[i].startswith("-") and args[i] not in ("-c", "-m", "-"):
        flags.append(args[i]); i += 1
    if not {"-I", "-E", "-S"} & {"-" + ch for f in flags for ch in f[1:]}:
        return args
    if i >= len(args) or args[i] == "-":
        return None
    jail = str(JAIL_DIR)
    if args[i] == "-c":
        boot = _JAIL_BOOT.format(jail=jail, argv=["-c", *args[i + 2:]])
        code = boot + f"exec(compile({args[i + 1]!r},'<string>','exec'),{{'__name__':'__main__'}})"
    elif args[i] == "-m":
        boot = _JAIL_BOOT.format(jail=jail, argv=[args[i + 1], *args[i + 2:]])
        code = boot + f"runpy.run_module({args[i + 1]!r},run_name='__main__',alter_sys=True)"
    else:
        boot = _JAIL_BOOT.format(jail=jail, argv=args[i:])
        code = boot + f"runpy.run_path({args[i]!r},run_name='__main__')"
    return [args[0], *flags, "-c", code]


def _dk_cmd(args) -> bool:
    if isinstance(args, (bytes, str)):
        parts = [args.decode() if isinstance(args, bytes) else args]
    else:
        parts = [a.decode() if isinstance(a, bytes) else str(a) for a in args]
    text = " ".join(parts).lower()
    return bool(re.search(r"\b(curl|wget)\b", text)) and (
        "draftkings" in text or any(ip in text for ip in (_DK_IPS or ())))


def _audit_args_list(args):
    if args is None:
        return []
    if isinstance(args, (str, bytes, os.PathLike)):
        return [os.fsdecode(args)]
    return [os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a) for a in args]


def _audit_check(event, args):
    """t260 audit-hook checker: non-loopback socket ops and network/DK child processes."""
    def deny(host):
        where = f"audit:{event}"
        if _is_dk(host if isinstance(host, (str, bytes)) else str(host)):
            raise DraftKingsBlocked(f"LIVE_DK_REQUEST_BLOCKED:{where}:{host}")
        raise DraftKingsBlocked(f"LIVE_NETWORK_BLOCKED:{where}:{host}")

    if event == "socket.getaddrinfo":
        host = args[0]
        if _is_dk(host) or not _is_local(host):
            deny(host)
        return
    if event in ("socket.gethostbyname", "socket.gethostbyaddr"):
        host = args[0]
        if _is_dk(host) or not _is_local(host):
            deny(host)
        return
    if event in ("socket.__new__", "socket.gethostname", "socket.getservbyname",
                 "socket.getservbyport", "socket.sethostname"):
        return                                  # no peer address (local table/namespace ops)
    if event == "socket.getnameinfo":
        addr = args[0]
    elif event.startswith("socket."):           # connect / sendto / sendmsg / bind: (self, address)
        addr = args[-1]
    if event.startswith("socket."):
        if isinstance(addr, tuple) and addr and isinstance(addr[0], (str, bytes)):
            host = addr[0]
            if event == "socket.bind" and host in ("", b""):
                deny("0.0.0.0")
            if _is_dk(host) or not _is_local(host):
                deny(host)
        return                                  # AF_UNIX paths: documented residual
    if event in ("os.fork", "os.forkpty"):
        return                                  # no new program; its exec/spawn is checked
    if event == "os.system":
        cmd = os.fsdecode(args[0]) if args and args[0] is not None else ""
        if _dk_cmd(cmd) or _is_dk(cmd) or any(_is_dk(urllib.parse.urlsplit(t).hostname)
                                               for t in cmd.split() if "://" in t):
            raise DraftKingsBlocked(f"LIVE_DK_REQUEST_BLOCKED:audit:{event}:{cmd}")
        if _fallback_net_cmd(cmd):
            raise DraftKingsBlocked(f"LIVE_NETWORK_BLOCKED:audit:{event}:{cmd}")
        return
    if event == "pty.spawn":
        exe, argv = None, _audit_args_list(args[0])
    elif event == "os.startfile":
        exe, argv = args[0], _audit_args_list(args[2]) if len(args) > 2 and args[2] else []
    elif event == "subprocess.Popen":
        exe, argv = args[0], _audit_args_list(args[1])
    elif event == "os.posix_spawn":
        exe, argv = args[0], _audit_args_list(args[1])
    else:                                       # os.exec / os.spawn: (path, args, env) / (mode, path, args, env)
        off = 1 if event == "os.spawn" else 0
        exe, argv = args[off], _audit_args_list(args[off + 1])
    pre = _unshare_prefix()
    if pre and argv[:len(pre)] == pre:
        return                                  # already inside the empty namespace
    full = ([os.fsdecode(exe)] if exe is not None else []) + argv
    if _dk_cmd(full) or any(_is_dk(urllib.parse.urlsplit(a).hostname) for a in full if "://" in a):
        raise DraftKingsBlocked(f"LIVE_DK_REQUEST_BLOCKED:audit:{event}:{full}")
    shell_text = argv[2:3] if len(argv) >= 3 and argv[1] == "-c" and os.path.basename(argv[0]) in ("sh", "bash", "dash") else []
    if _fallback_net_cmd(full) or (exe is not None and _is_net_binary_file(exe)) or any(
            _fallback_net_cmd(t) for t in shell_text):
        raise DraftKingsBlocked(f"LIVE_NETWORK_BLOCKED:audit:{event}:{full}")


def _net_audit_state():
    st = sys.modules.get("sportsedge_net_audit")
    if st is None:                               # run without tests/conftest.py
        import importlib.util
        spec = importlib.util.spec_from_file_location("sportsedge_net_audit", JAIL_DIR / "audit_hook.py")
        st = importlib.util.module_from_spec(spec)
        sys.modules["sportsedge_net_audit"] = st
        spec.loader.exec_module(st)
    st.install()
    st.STATE.checker = _audit_check
    return st


_net_audit_state()


@pytest.fixture
def dk_block(monkeypatch):
    global _DK_IPS
    if _DK_IPS is None:          # resolve before the audit hook goes active (as in t259)
        _DK_IPS = _resolve_dk_ips()
    _ctx = _net_audit_state().active()
    _ctx.__enter__()
    try:
        yield from _dk_block_body(monkeypatch)
    finally:
        _ctx.__exit__(None, None, None)


def _dk_block_body(monkeypatch):
    global _DK_IPS
    if _DK_IPS is None:
        _DK_IPS = _resolve_dk_ips()
    attempts = []

    def refuse(where, host):
        attempts.append((where, str(host)))
        raise DraftKingsBlocked(f"LIVE_DK_REQUEST_BLOCKED:{where}:{host}")

    real_gai, real_cc, real_connect = socket.getaddrinfo, socket.create_connection, socket.socket.connect

    def refuse_net(where, host):
        attempts.append((where, str(host)))
        raise DraftKingsBlocked(f"LIVE_NETWORK_BLOCKED:{where}:{host}")

    def check(where, host):
        if _is_dk(host):
            refuse(where, host)
        if not _is_local(host):
            refuse_net(where, host)

    def gai(host, *a, **k):
        check("getaddrinfo", host)
        return real_gai(host, *a, **k)

    def cc(address, *a, **k):
        check("create_connection", address[0])
        return real_cc(address, *a, **k)

    def _inet(sock, address):
        return sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple)

    def connect(self, address):
        if _inet(self, address):
            check("socket.connect", address[0])
        return real_connect(self, address)

    real_connect_ex, real_sendto = socket.socket.connect_ex, socket.socket.sendto

    def connect_ex(self, address):
        if _inet(self, address):
            check("socket.connect_ex", address[0])
        return real_connect_ex(self, address)

    def sendto(self, data, *args):
        if _inet(self, args[-1]):
            check("socket.sendto", args[-1][0])
        return real_sendto(self, data, *args)

    real_urlopen = urllib.request.urlopen

    def urlopen(url, *a, **k):
        full = url.full_url if isinstance(url, urllib.request.Request) else str(url)
        if _is_dk(urllib.parse.urlsplit(full).hostname):
            refuse("urlopen", full)
        return real_urlopen(url, *a, **k)

    monkeypatch.setattr(socket, "getaddrinfo", gai)
    monkeypatch.setattr(socket, "create_connection", cc)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", sendto)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    # t259 layer 2: the C-level _socket module (covers _socket.socket() and a reloaded
    # socket module, which rebuilds itself from _socket) and every os spawn/exec entry.
    import _socket
    real_raw = _socket.socket

    class _GuardedRawSocket(real_raw):
        __slots__ = ()   # a reloaded socket.py adds __weakref__ itself
        def connect(self, address):
            if _inet(self, address):
                check("_socket.connect", address[0])
            return super().connect(address)

        def connect_ex(self, address):
            if _inet(self, address):
                check("_socket.connect_ex", address[0])
            return super().connect_ex(address)

        def sendto(self, data, *args):
            if _inet(self, args[-1]):
                check("_socket.sendto", args[-1][0])
            return super().sendto(data, *args)

    real_raw_gai = _socket.getaddrinfo

    def raw_gai(host, *a, **k):
        check("_socket.getaddrinfo", host)
        return real_raw_gai(host, *a, **k)

    monkeypatch.setattr(_socket, "socket", _GuardedRawSocket)
    monkeypatch.setattr(_socket, "SocketType", _GuardedRawSocket)
    monkeypatch.setattr(_socket, "getaddrinfo", raw_gai)

    def exec_check(fn, path, argv):
        argv = [os.fsdecode(a) for a in (argv or ())]
        path = os.fsdecode(path)
        pre = _unshare_prefix()
        if pre and argv[:len(pre)] == pre:
            return                                  # already wrapped in the empty namespace
        if _dk_cmd([path, *argv]):
            refuse(fn, [path, *argv])
        if _fallback_net_cmd([path, *argv]) or _fallback_net_cmd(argv):
            refuse_net(fn, [path, *argv])

    def _wrap(fn, has_mode):
        real = getattr(os, fn)

        def guarded(*a, **k):
            off = 1 if has_mode else 0
            exec_check(fn, a[off], a[off + 1] if len(a) > off + 1 else k.get("argv", ()))
            return real(*a, **k)
        monkeypatch.setattr(os, fn, guarded)

    for fn in ("posix_spawn", "posix_spawnp", "execv", "execve", "execvp", "execvpe"):
        if hasattr(os, fn):
            _wrap(fn, False)
    for fn in ("spawnv", "spawnve", "spawnvp", "spawnvpe"):
        if hasattr(os, fn):
            _wrap(fn, True)
    def _wrap_l(fn, has_mode, env_last):
        real = getattr(os, fn)

        def guarded(*a):
            off = 1 if has_mode else 0
            argv = a[off + 1:-1] if env_last else a[off + 1:]
            exec_check(fn, a[off], argv)
            return real(*a)
        monkeypatch.setattr(os, fn, guarded)

    for fn, has_mode, env_last in (("execl", False, False), ("execle", False, True),
                                   ("execlp", False, False), ("execlpe", False, True),
                                   ("spawnl", True, False), ("spawnle", True, True),
                                   ("spawnlp", True, False), ("spawnlpe", True, True)):
        if hasattr(os, fn):
            _wrap_l(fn, has_mode, env_last)

    # t262: the one known private launcher. subprocess binds it at import as _fork_exec.
    import _posixsubprocess
    real_fork_exec = _posixsubprocess.fork_exec

    def fork_exec(args, executable_list, *rest):
        argv = _audit_args_list(args)
        pre = _unshare_prefix()
        if not (pre and argv[:len(pre)] == pre):
            exe = os.fsdecode(executable_list[0]) if executable_list else (argv[0] if argv else "")
            if _dk_cmd([exe, *argv]) or any(_is_dk(urllib.parse.urlsplit(a).hostname) for a in argv if "://" in a):
                refuse("_posixsubprocess.fork_exec", argv)
            if _fallback_net_cmd([exe, *argv]) or _fallback_net_cmd(argv) or _is_net_binary_file(exe):
                refuse_net("_posixsubprocess.fork_exec", argv)
        return real_fork_exec(args, executable_list, *rest)

    fork_exec._sportsedge_net_guard = True
    monkeypatch.setattr(_posixsubprocess, "fork_exec", fork_exec)
    if hasattr(subprocess, "_fork_exec"):
        monkeypatch.setattr(subprocess, "_fork_exec", fork_exec)

    real_popen_init = subprocess.Popen.__init__

    prefix = _unshare_prefix()
    blocked_child = [sys.executable, "-c",
                     "import sys;sys.stderr.write('LIVE_NETWORK_BLOCKED\\n');sys.exit(97)"]

    def child_env(base):
        # children only (never this process, so in-process DK calls still hit the socket
        # guard instead of a proxy): dead proxy for proxy-aware tools, jail for child Python
        env = dict(os.environ if base is None else base)
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                    "all_proxy", "FTP_PROXY", "ftp_proxy"):
            env[var] = DEAD_PROXY
        env["NO_PROXY"] = env["no_proxy"] = ""
        pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(p for p in (str(JAIL_DIR), pp) if p)
        return env

    def popen_init(self, args, *a, **k):
        if _dk_cmd(args):
            refuse("subprocess", args)
        if len(a) > 9:
            a = a[:9] + (child_env(a[9]),) + a[10:]
        else:
            k["env"] = child_env(k.get("env"))
        shell = k.get("shell", False) or (len(a) > 8 and a[8])
        if prefix:                      # every child runs in an empty network namespace
            if shell:
                k["shell"] = False
                args = prefix + ["/bin/sh", "-c", args if isinstance(args, (str, bytes)) else " ".join(map(str, args))]
                if len(a) > 8:
                    a = a[:8] + (False,) + a[9:]
            else:
                args = prefix + ([args] if isinstance(args, (str, bytes)) else list(args))
        else:
            jailed = None if shell else _jail_isolated_python(args)
            if (shell or jailed is not None) and not _fallback_net_cmd(args):
                args = jailed if jailed is not None else args
            else:
                attempts.append(("subprocess-fallback", str(args)))
                args, k["shell"] = list(blocked_child), False
                k.pop("executable", None)
        return real_popen_init(self, args, *a, **k)

    def system(cmd):
        if _dk_cmd(cmd):
            refuse("os.system", cmd)
        return subprocess.call(cmd, shell=True)

    monkeypatch.setattr(subprocess.Popen, "__init__", popen_init)
    monkeypatch.setattr(os, "system", system)
    try:
        import requests
        real_req = requests.sessions.Session.request

        def req(self, method, url, *a, **k):
            if _is_dk(urllib.parse.urlsplit(str(url)).hostname):
                refuse("requests", url)
            return real_req(self, method, url, *a, **k)
        monkeypatch.setattr(requests.sessions.Session, "request", req)
    except ImportError:
        pass
    monkeypatch.chdir(ROOT)
    monkeypatch.syspath_prepend(str(ROOT))
    yield attempts


def test_guard_blocks_a_real_dk_fetch(dk_block):
    """Control: the module the live probes use is stopped before any connection."""
    from sportsedge import draftkings_game_market_source as g
    with pytest.raises(Exception):
        g.fetch_board("americanfootball_nfl")
    assert dk_block, "fetch_board was not intercepted"


def test_guard_blocks_low_level_socket(dk_block):
    with pytest.raises(DraftKingsBlocked):
        socket.create_connection(("sportsbook-nash.draftkings.com", 443), timeout=1)
    with pytest.raises(DraftKingsBlocked):
        socket.getaddrinfo("api.draftkings.com", 443)


def test_guard_blocks_curl_and_wget(dk_block):
    for cmd in (["curl", "-s", "https://sportsbook-nash.draftkings.com/api/x"],
                "wget -q https://api.draftkings.com/contests/v1/contests/1",
                ["/usr/bin/curl", "https://sportsbook.draftkings.com/sites/US-SB/api/v5"]):
        with pytest.raises(DraftKingsBlocked):
            subprocess.run(cmd, shell=isinstance(cmd, str))
    with pytest.raises(DraftKingsBlocked):
        os.system("curl https://api.draftkings.com/x")
    assert len(dk_block) == 4
    assert subprocess.run(["true"]).returncode == 0   # unrelated commands still run


def test_guard_blocks_resolved_dk_ips(dk_block):
    if not _DK_IPS:
        pytest.skip("DK hosts did not resolve here; IP blocking not exercisable")
    ip = sorted(_DK_IPS)[0]
    with pytest.raises(DraftKingsBlocked):
        socket.create_connection((ip, 443), timeout=1)
    with pytest.raises(DraftKingsBlocked):
        subprocess.run(["curl", f"https://{ip}/"])


@pytest.mark.parametrize("wf,mod,fn", [(w, m, f) for w, xs in SELF_TESTS.items() for m, f in xs])
def test_ci_self_test_makes_no_live_dk_request(dk_block, wf, mod, fn):
    sys.modules.pop(mod, None)
    assert getattr(importlib.import_module(mod), fn)() == 0
    assert dk_block == []


@pytest.mark.parametrize("module", MODULES)
def test_ci_test_module_makes_no_live_dk_request(dk_block, module):
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    assert result.testsRun > 0
    assert dk_block == [], dk_block
    blocked = [str(e) for _, e in result.errors + result.failures if "LIVE_DK_REQUEST_BLOCKED" in e]
    assert blocked == []


@pytest.mark.parametrize("module", sorted({m for ms in IMPORT_ONLY_SCRIPTS.values() for m in ms}))
def test_import_only_script_makes_no_live_dk_request_on_import(dk_block, module):
    sys.modules.pop(module, None)
    importlib.import_module(module)
    assert dk_block == []


def test_guarded_list_matches_workflows():
    wf = ROOT / ".github" / "workflows"
    for name, mods in {**GUARDED, **IMPORT_ONLY_SCRIPTS,
                       **{w: [m for m, _ in xs] for w, xs in SELF_TESTS.items()}}.items():
        text = (wf / name).read_text(encoding="utf-8")
        assert "draftkings" not in "".join(
            l for l in text.splitlines() if "curl" in l).lower(), name
        for m in mods:
            stem = m.split(".")[-1]
            assert stem in text or "test_nfl*.py" in text or "test_football*.py" in text, (name, m)


# --- t258: bypasses found by the t255 audit (LOW). Every check below targets a NON-DK
# host (or a pure function), so neither the RED run nor any CI run ever touches DraftKings.
_JAIL_RESULTS = {}


def _load_run_jailed():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_run_jailed", JAIL_DIR / "run_jailed.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


class _Jail:
    def __init__(self, delegated):
        self.delegated = delegated


@pytest.fixture
def net_jail(request):
    """Layer 1. Inside the jail: assert only loopback exists, then run the bypass for real.
    Outside: re-launch this module's jailed bypass tests once in a pytest session under
    `unshare -rn` and require this test to have passed there. No unshare -> SKIP with
    NET_JAIL_UNAVAILABLE (never a pass)."""
    if os.environ.get("SPORTSEDGE_NET_JAILED") == "1":
        ifaces = _load_run_jailed().interfaces()
        assert ifaces == ["lo"], f"NET_JAIL_BROKEN: interfaces {ifaces}"
        return _Jail(False)
    rj = _load_run_jailed()
    if rj.unshare_prefix() is None:
        pytest.skip("NET_JAIL_UNAVAILABLE: unshare -rn not permitted here; isolation not claimed")
    if not _JAIL_RESULTS:
        import tempfile
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as td:
            xml = os.path.join(td, "jail.xml")
            r = subprocess.run(rj.jailed_argv([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                               __file__, "-k", "bypass and jailed", f"--junitxml={xml}"]),
                               cwd=ROOT, env=rj.jailed_env(), capture_output=True, text=True, timeout=600)
            _JAIL_RESULTS["_out"] = r.stdout[-3000:] + r.stderr[-1000:]
            if os.path.exists(xml):
                for tc in ET.parse(xml).iter("testcase"):
                    bad = [c.tag for c in tc if c.tag in ("failure", "error", "skipped")]
                    _JAIL_RESULTS[tc.get("name")] = bad[0] if bad else "passed"
    got = _JAIL_RESULTS.get(request.node.name)
    assert got == "passed", f"jailed run: {request.node.name} -> {got}\n{_JAIL_RESULTS.get('_out')}"
    return _Jail(True)


_PROBE = "example.com"   # stands in for any host: the jail must block ALL egress


def _child_py(code):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)


def test_child_python_process_cannot_connect(dk_block):
    r = _child_py(f"import socket;socket.create_connection(({_PROBE!r},443),5);print('CONNECTED')")
    assert "CONNECTED" not in r.stdout and r.returncode != 0, r.stdout


def test_child_python_urlopen_cannot_reach_network(dk_block):
    r = _child_py(f"import urllib.request;urllib.request.urlopen('https://{_PROBE}/',timeout=5);print('CONNECTED')")
    assert "CONNECTED" not in r.stdout and r.returncode != 0


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_openssl_s_client_cannot_connect(dk_block):
    r = subprocess.run(["openssl", "s_client", "-connect", f"{_PROBE}:443", "-brief"],
                       input="", capture_output=True, text=True, timeout=30)
    assert "CONNECTION ESTABLISHED" not in (r.stdout + r.stderr) and r.returncode != 0


@pytest.mark.skipif(shutil.which("nc") is None, reason="nc not installed")
def test_nc_cannot_connect(dk_block):
    r = subprocess.run(["nc", "-z", "-w", "5", _PROBE, "443"], capture_output=True, timeout=30)
    assert r.returncode != 0


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_bash_dev_tcp_cannot_connect(dk_block):
    r = subprocess.run(f"bash -c 'exec 3<>/dev/tcp/{_PROBE}/443 && echo CONNECTED'",
                       shell=True, capture_output=True, text=True, timeout=30)
    assert "CONNECTED" not in r.stdout


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl not installed")
def test_curl_percent_encoded_host_cannot_connect(dk_block):
    r = subprocess.run(["curl", "-sS", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}",
                        "https://ex%61mple.com/"], capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 or r.stdout in ("", "000")


def test_percent_encoded_dk_host_detected():
    assert _is_dk("api.%64raftkings.com")
    assert _is_dk("API.%44RAFTKINGS.COM")
    assert _is_dk(b"sportsbook.%64%72aftkings.com")


def test_in_process_any_non_loopback_host_refused(dk_block):
    with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED"):
        socket.create_connection((_PROBE, 443), timeout=5)


def test_literal_ip_refused_even_when_dk_ips_unresolved(dk_block, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "_DK_IPS", frozenset())
    with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED"):
        socket.create_connection(("203.0.113.7", 443), timeout=5)   # TEST-NET-3


def test_children_inherit_dead_proxy_env(dk_block):
    r = _child_py("import os;print(os.environ.get('HTTPS_PROXY',''),os.environ.get('ALL_PROXY',''))")
    assert r.stdout.split() == ["http://127.0.0.1:9", "http://127.0.0.1:9"]


def test_loopback_still_allowed(dk_block):
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    try:
        socket.create_connection(srv.getsockname(), timeout=5).close()
    finally:
        srv.close()


def test_bypasses_also_blocked_in_no_namespace_fallback_mode():
    """Runners without unprivileged user namespaces get the fallback jail (dead proxy,
    child-Python sitecustomize, network-binary refusal); the same bypass tests must pass."""
    if os.environ.get("SPORTSEDGE_NET_JAIL_FORCE_FALLBACK") == "1":
        pytest.skip("already the fallback run")
    env = {**os.environ, "SPORTSEDGE_NET_JAIL_FORCE_FALLBACK": "1"}
    k = ("(child or openssl or nc_ or bash or percent or non_loopback or literal or proxy "
         "or loopback or curl_and_wget or low_level) and not jailed")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", __file__,
                        "-k", k], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:]
    assert " passed" in r.stdout and " failed" not in r.stdout


def test_fallback_detector_flags_each_audit_bypass():
    for cmd in (["openssl", "s_client", "-connect", "x:443"], ["nc", "x", "443"],
                "bash -c 'exec 3<>/dev/tcp/x/443'", ["/usr/bin/ncat", "x", "443"],
                f"{sys.executable} -I -c pass", "socat - TCP:x:443",
                ["curl", "https://api.%64raftkings.com/"]):
        assert _fallback_net_cmd(cmd), cmd
    for cmd in (["true"], "echo ok", [sys.executable, "-c", "pass"], ["git", "status"]):
        assert not _fallback_net_cmd(cmd), cmd


def test_fallback_isolated_python_child_is_jailed_not_skipped(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text("import socket,sys\ntry:\n    socket.create_connection(('example.com',443),5)\n"
                      "    print('CONNECTED')\nexcept OSError as e:\n    print('BLOCKED', e)\n"
                      "print('ARGV', sys.argv[1:])\n", encoding="utf-8")
    for argv in ([sys.executable, "-I", str(script), "a"], [sys.executable, "-I", "-S", str(script), "a"],
                 [sys.executable, "-E", "-c", script.read_text(encoding="utf-8"), "a"]):
        r = subprocess.run(_jail_isolated_python(argv), capture_output=True, text=True, timeout=60)
        assert "LIVE_NETWORK_BLOCKED" in r.stdout and "CONNECTED" not in r.stdout, r.stdout + r.stderr
        assert "ARGV ['a']" in r.stdout


# ---- t259: audit bypasses of the t258 jail (7b099d35), one test per bypass -------------
# Layer 1 (isolation): the bypass runs inside a pytest session re-launched under
# `unshare -rn` (empty network namespace). Without unshare these tests SKIP with
# NET_JAIL_UNAVAILABLE instead of claiming isolation. Layer 2 (in-process): _socket,
# os.posix_spawn*/spawn*/exec* are patched too. Probes target example.com only, never DK.

def test_bypass1_raw__socket_connect_jailed(net_jail):
    if net_jail.delegated:
        return
    r = _child_py(f"import _socket;s=_socket.socket();s.settimeout(5);s.connect(({_PROBE!r},443));print('CONNECTED')")
    assert "CONNECTED" not in r.stdout and r.returncode != 0
    import _socket
    s = _socket.socket(); s.settimeout(5)
    try:
        with pytest.raises(OSError):
            s.connect((_PROBE, 443))
    finally:
        s.close()


def test_bypass1_raw__socket_connect_in_process_refused(dk_block):
    import _socket
    s = _socket.socket(); s.settimeout(5)
    try:
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED"):
            s.connect((_PROBE, 443))
    finally:
        s.close()


def _reload_socket_and_connect():
    saved = dict(socket.__dict__)
    try:
        fresh = importlib.reload(socket)
        return fresh.create_connection((_PROBE, 443), timeout=5)
    finally:
        socket.__dict__.clear(); socket.__dict__.update(saved)


def test_bypass2_reload_socket_create_connection_jailed(net_jail):
    if net_jail.delegated:
        return
    with pytest.raises(OSError):
        _reload_socket_and_connect().close()


def test_bypass2_reload_socket_create_connection_in_process_refused(dk_block):
    with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED"):
        _reload_socket_and_connect().close()


def _posix_spawn_curl():
    curl = shutil.which("curl")
    if curl is None:
        pytest.skip("curl not installed")
    r, w = os.pipe()
    try:
        pid = os.posix_spawn(curl, [curl, "-sS", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}",
                                    f"https://{_PROBE}/"], dict(os.environ),
                             file_actions=[(os.POSIX_SPAWN_DUP2, w, 1)])
        os.close(w); w = -1
        _, status = os.waitpid(pid, 0)
        return os.read(r, 100).decode(), os.waitstatus_to_exitcode(status)
    finally:
        os.close(r)
        if w >= 0:
            os.close(w)


def test_bypass3_posix_spawn_curl_jailed(net_jail):
    if net_jail.delegated:
        return
    out, code = _posix_spawn_curl()
    assert code != 0 and out in ("", "000"), (out, code)


def test_bypass3_posix_spawn_and_exec_family_refused_in_process(dk_block):
    curl = shutil.which("curl") or "/usr/bin/curl"
    for fn, call in (("posix_spawn", lambda: os.posix_spawn(curl, [curl, f"https://{_PROBE}/"], {})),
                     ("posix_spawnp", lambda: os.posix_spawnp("curl", ["curl", f"https://{_PROBE}/"], {})),
                     ("spawnv", lambda: os.spawnv(os.P_WAIT, curl, [curl, f"https://{_PROBE}/"])),
                     ("spawnlp", lambda: os.spawnlp(os.P_WAIT, "curl", "curl", f"https://{_PROBE}/")),
                     ("execv", lambda: os.execv(curl, [curl, f"https://{_PROBE}/"])),
                     ("execvpe", lambda: os.execvpe("curl", ["curl", f"https://{_PROBE}/"], {}))):
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED"):
            call()
        assert any(fn in w for w, _ in dk_block), fn


def _renamed_curl(tmp_path):
    curl = shutil.which("curl")
    if curl is None:
        pytest.skip("curl not installed")
    dst = tmp_path / "fetchtool"
    shutil.copy2(curl, dst)
    return str(dst)


def test_bypass4_renamed_curl_noproxy_jailed(net_jail, tmp_path):
    if net_jail.delegated:
        return
    r = subprocess.run([_renamed_curl(tmp_path), "--noproxy", "*", "-sS", "-m", "5", "-o", "/dev/null",
                        "-w", "%{http_code}", f"https://{_PROBE}/"], capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and r.stdout in ("", "000"), r.stdout


def test_bypass4_renamed_curl_refused_by_content_in_fallback(tmp_path):
    assert _fallback_net_cmd([_renamed_curl(tmp_path), "--noproxy", "*", f"https://{_PROBE}/"])


def test_fallback_mode_skips_live_tests_with_net_jail_unavailable():
    """No namespace -> the live bypass tests must SKIP (NET_JAIL_UNAVAILABLE), never pass."""
    if os.environ.get("SPORTSEDGE_NET_JAIL_FORCE_FALLBACK") == "1" or os.environ.get("SPORTSEDGE_NET_JAILED") == "1":
        pytest.skip("nested run")
    env = {**os.environ, "SPORTSEDGE_NET_JAIL_FORCE_FALLBACK": "1"}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", __file__,
                        "-k", "bypass and jailed"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:]
    assert "4 skipped" in r.stdout and " passed" not in r.stdout, r.stdout[-2000:]
    assert r.stdout.count("NET_JAIL_UNAVAILABLE") >= 4, r.stdout[-2000:]


def test_jailed_session_has_only_loopback():
    """The re-exec wrapper really runs pytest in an empty network namespace."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_run_jailed", JAIL_DIR / "run_jailed.py")
    run_jailed = importlib.util.module_from_spec(spec); spec.loader.exec_module(run_jailed)
    if run_jailed.unshare_prefix() is None:
        pytest.skip("NET_JAIL_UNAVAILABLE")
    r = subprocess.run(run_jailed.jailed_argv([sys.executable, "-c",
                       run_jailed._IFACES]),
                       capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "['lo']", r.stdout + r.stderr


# ---- t260: audit-hook layer (sys.addaudithook) for routes that reach the real C socket ----
# socket.socket.__bases__[0] and _socket.socket.__mro__[1] are the unpatched C type; the
# audit events socket.connect/getaddrinfo/sendto/bind, subprocess.Popen and os.posix_spawn
# fire inside C, so the hook refuses them. One test per route; probes use example.com only.

def _route_refused(event):
    """Outside the jail the audit hook must refuse. Inside the empty namespace C resolves the
    hostname before the audit event fires, so name-resolution failure is the refusal there."""
    import contextlib
    if os.environ.get("SPORTSEDGE_NET_JAILED") == "1":
        return pytest.raises((DraftKingsBlocked, socket.gaierror))
    return pytest.raises(DraftKingsBlocked, match=f"LIVE_NETWORK_BLOCKED:audit:{event}")


def _net_audit():
    return sys.modules["sportsedge_net_audit"]


def test_audit_hook_installed_for_whole_session_and_gated_off_outside_guard():
    st = _net_audit().STATE
    assert st.installed and not st.active
    st.hook("socket.connect", (None, (_PROBE, 443)))   # inactive: must not raise


def test_route_bases0_connect_refused_by_audit_hook(dk_block):
    s = socket.socket.__bases__[0](socket.AF_INET, socket.SOCK_STREAM); s.settimeout(5)
    try:
        with _route_refused("socket.connect"):
            s.connect((_PROBE, 443))
    finally:
        s.close()


def test_route_mro1_connect_refused_by_audit_hook(dk_block):
    import _socket
    s = _socket.socket.__mro__[1](socket.AF_INET, socket.SOCK_STREAM); s.settimeout(5)
    try:
        with _route_refused("socket.connect"):
            s.connect((_PROBE, 443))
    finally:
        s.close()


def test_route_reload_socket_refused_by_audit_hook_alone():
    """Hook only (no monkeypatch layer): reload(socket)+create_connection is still refused."""
    with _net_audit().active():
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:socket.getaddrinfo"):
            _reload_socket_and_connect().close()


def test_route_raw_c_getaddrinfo_refused_by_audit_hook(dk_block):
    import importlib.util
    spec = importlib.util.find_spec("_socket")
    fresh = importlib.util.module_from_spec(spec)        # a new, unpatched _socket instance
    with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:socket.getaddrinfo"):
        fresh.getaddrinfo(_PROBE, 443)


def test_route_bases0_sendto_refused_by_audit_hook(dk_block):
    s = socket.socket.__bases__[0](socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with _route_refused("socket.sendto"):
            s.sendto(b"x", (_PROBE, 9))
    finally:
        s.close()


def test_route_bases0_bind_non_loopback_refused_loopback_allowed(dk_block):
    s = socket.socket.__bases__[0](socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:socket.bind"):
            s.bind(("0.0.0.0", 0))
    finally:
        s.close()
    s = socket.socket.__bases__[0](socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
    finally:
        s.close()


def test_route_posix_module_posix_spawn_refused_by_audit_hook(dk_block):
    import posix
    curl = shutil.which("curl") or "/usr/bin/curl"
    with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:os.posix_spawn"):
        posix.posix_spawn(curl, [curl, "-m", "5", f"https://{_PROBE}/"], {})


def test_route_unwrapped_popen_refused_by_audit_hook_alone():
    with _net_audit().active():
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:subprocess.Popen"):
            subprocess.run(["curl", "-m", "5", f"https://{_PROBE}/"], capture_output=True, timeout=30)
        with pytest.raises(DraftKingsBlocked, match="LIVE_DK_REQUEST_BLOCKED:audit:subprocess.Popen"):
            subprocess.run(["true", "https://api.%64raftkings.com/"], capture_output=True, timeout=30)


# ---- t261: os.system audit route, every process-launch event, thread-safe gating ----------
# CPython process-launch audit events (sys audit events table, 3.8-3.13).
_CPYTHON_PROCESS_LAUNCH_EVENTS = {"os.exec", "os.fork", "os.forkpty", "os.posix_spawn", "os.spawn",
                                  "os.startfile", "os.system", "pty.spawn", "subprocess.Popen"}


def test_every_cpython_process_launch_audit_event_is_hooked():
    missing = _CPYTHON_PROCESS_LAUNCH_EVENTS - set(_net_audit()._EVENTS)
    assert not missing, missing


def test_posix_system_curl_refused_inside_dk_block(dk_block):
    """Auditor repro: posix.system skips the os.system monkeypatch; the audit hook refuses it."""
    import posix
    with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:os.system"):
        posix.system(f"curl -sS -m 5 -o /dev/null https://{_PROBE}/")


def test_os_system_command_text_routed_through_fallback_detector():
    import posix
    with _net_audit().active():
        with pytest.raises(DraftKingsBlocked, match="LIVE_DK_REQUEST_BLOCKED:audit:os.system"):
            posix.system("true https://api.%64raftkings.com/")
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:os.system"):
            posix.system(f"bash -c 'exec 3<>/dev/tcp/{_PROBE}/443'")
        assert posix.system("true") == 0


def test_pty_spawn_and_startfile_events_checked():
    st = _net_audit().STATE
    with _net_audit().active():
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:pty.spawn"):
            st.hook("pty.spawn", (["curl", f"https://{_PROBE}/"],))
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:audit:os.startfile"):
            st.hook("os.startfile", ("curl", "open"))
        st.hook("os.fork", ())          # fork alone launches no new program


def test_gate_not_dropped_for_other_threads_while_one_thread_checks():
    """LOW race: a check in progress on one thread must not switch the hook off for others."""
    import threading
    st = _net_audit().STATE
    entered, release = threading.Event(), threading.Event()
    real = st.checker

    def slow(event, args):
        if args and args[-1] == ("hold.invalid", 1):
            entered.set(); release.wait(10)
            return
        return real(event, args)

    st.checker = slow
    try:
        with _net_audit().active():
            t = threading.Thread(target=st.hook, args=("socket.connect", (None, ("hold.invalid", 1))))
            t.start()
            assert entered.wait(10)
            try:
                with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED"):
                    st.hook("socket.connect", (None, (_PROBE, 443)))
            finally:
                release.set(); t.join(10)
    finally:
        st.checker = real


# ---- t262: every socket.* audit event, _posixsubprocess.fork_exec, jail for DK tests -------
_DOCS_EVENTS = JAIL_DIR / "cpython_3_12_audit_events.txt"


def _docs_events(prefix=""):
    names = [l.strip() for l in _DOCS_EVENTS.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    return {n for n in names if n.startswith(prefix)}


def test_docs_event_list_matches_running_python_series():
    assert sys.version_info[:2] == (3, 12), "re-vendor the audit events table for this Python"
    assert {"socket.connect", "socket.sendmsg", "os.system", "subprocess.Popen"} <= _docs_events()


def test_every_documented_socket_audit_event_is_handled():
    docs = _docs_events("socket.")
    assert len(docs) >= 13, docs
    missing = docs - set(_net_audit()._EVENTS)
    assert not missing, missing


def test_every_documented_process_launch_event_is_handled():
    launch = {e for e in _docs_events() if e in _CPYTHON_PROCESS_LAUNCH_EVENTS or e.startswith(
        ("os.exec", "os.spawn", "os.posix_spawn", "os.fork", "pty.", "subprocess."))} | {"os.system", "os.startfile"}
    assert not (launch - set(_net_audit()._EVENTS))


def test_socket_name_and_address_events_refuse_non_loopback():
    st = _net_audit().STATE
    with _net_audit().active():
        for event, args in (("socket.sendmsg", (None, (_PROBE, 9))),
                            ("socket.gethostbyname", (_PROBE,)),
                            ("socket.gethostbyaddr", ("203.0.113.7",)),
                            ("socket.getnameinfo", ((_PROBE, 443),))):
            with pytest.raises(DraftKingsBlocked, match=f"LIVE_NETWORK_BLOCKED:audit:{event}"):
                st.hook(event, args)
        for event, args in (("socket.sendmsg", (None, None)), ("socket.sendmsg", (None, ("127.0.0.1", 9))),
                            ("socket.gethostbyname", ("localhost",)), ("socket.__new__", (None, 2, 1, 0)),
                            ("socket.gethostname", ()), ("socket.getservbyname", ("https", "tcp")),
                            ("socket.getservbyport", (443, "tcp"))):
            st.hook(event, args)


def test_real_sendmsg_refused_inside_dk_block(dk_block):
    s = socket.socket.__bases__[0](socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED"):
            s.sendmsg([b"x"], [], 0, ("203.0.113.7", 9))      # TEST-NET-3 literal, no DNS
    finally:
        s.close()


def _fork_exec_curl():
    import _posixsubprocess
    curl = shutil.which("curl") or "/usr/bin/curl"
    errr, errw = os.pipe()
    try:
        pid = _posixsubprocess.fork_exec(
            [curl, "-sS", "-m", "5", "-o", "/dev/null", f"https://{_PROBE}/"], [os.fsencode(curl)],
            True, (errw,), None, None, -1, -1, -1, -1, -1, -1, errr, errw, False, False,
            -1, None, None, -1, -1, None, False)
        os.close(errw); errw = -1
        os.waitpid(pid, 0)
        return pid
    finally:
        os.close(errr)
        if errw >= 0:
            os.close(errw)


def test_auditor_repro_posixsubprocess_fork_exec_curl_refused(dk_block):
    with pytest.raises(DraftKingsBlocked, match="LIVE_NETWORK_BLOCKED:_posixsubprocess.fork_exec"):
        _fork_exec_curl()


def test_subprocess_module_fork_exec_alias_is_guarded_too(dk_block):
    import _posixsubprocess
    assert subprocess._fork_exec is _posixsubprocess.fork_exec
    assert getattr(subprocess._fork_exec, "_sportsedge_net_guard", False)
    assert subprocess.run(["true"]).returncode == 0          # ordinary children still run


def test_guarded_dk_tests_run_inside_jail_where_available():
    if os.environ.get("SPORTSEDGE_NET_JAILED") == "1" or os.environ.get("SPORTSEDGE_NET_JAIL_FORCE_FALLBACK") == "1":
        pytest.skip("nested run")
    rj = _load_run_jailed()
    if rj.unshare_prefix() is None:
        pytest.skip("NET_JAIL_UNAVAILABLE")
    r = subprocess.run(rj.jailed_argv([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                       __file__, "-k", "guard_blocks or makes_no_live_dk_request"]),
                       cwd=ROOT, env=rj.jailed_env(), capture_output=True, text=True, timeout=600)
    assert r.returncode == 0 and " passed" in r.stdout and " failed" not in r.stdout, r.stdout[-2000:]
