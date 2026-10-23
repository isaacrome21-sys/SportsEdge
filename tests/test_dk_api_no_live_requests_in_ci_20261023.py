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


@pytest.fixture
def dk_block(monkeypatch):
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
    # children: dead proxy for proxy-aware tools, socket jail for every child Python
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                "all_proxy", "FTP_PROXY", "ftp_proxy"):
        monkeypatch.setenv(var, DEAD_PROXY)
    monkeypatch.setenv("NO_PROXY", ""); monkeypatch.setenv("no_proxy", "")
    pp = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(p for p in (str(JAIL_DIR), pp) if p))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    real_popen_init = subprocess.Popen.__init__

    prefix = _unshare_prefix()
    blocked_child = [sys.executable, "-c",
                     "import sys;sys.stderr.write('LIVE_NETWORK_BLOCKED\\n');sys.exit(97)"]

    def popen_init(self, args, *a, **k):
        if _dk_cmd(args):
            refuse("subprocess", args)
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
    return attempts


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
import shutil

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
    k = ("child or openssl or nc_ or bash or percent or non_loopback or literal or proxy "
         "or loopback or curl_and_wget or low_level")
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
