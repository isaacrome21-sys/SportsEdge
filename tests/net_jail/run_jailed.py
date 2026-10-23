"""Re-exec wrapper: run a command (default: the guarded pytest module) inside an empty
network namespace (`unshare -rn`) so no in-process trick (raw _socket, reload(socket),
os.posix_spawn, renamed binaries, --noproxy) can reach the network. t259, ruling 2026-10-23e.

    python tests/net_jail/run_jailed.py [pytest args...]

Sets SPORTSEDGE_NET_JAILED=1 inside the jail. If unshare -rn is unavailable it exits 3
with NET_JAIL_UNAVAILABLE and never claims isolation.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tests" / "test_dk_api_no_live_requests_in_ci_20261023.py"
_CACHE = []
# /proc/net/dev follows the caller's network namespace (/sys/class/net follows the sysfs mount)
_IFACES = "print(sorted(l.split(':')[0].strip() for l in open('/proc/net/dev').readlines()[2:]))"


def unshare_prefix():
    """['unshare','-rn'] when an unprivileged empty network namespace works, else None."""
    if os.environ.get("SPORTSEDGE_NET_JAIL_FORCE_FALLBACK") == "1":
        return None
    if not _CACHE:
        exe, ok = shutil.which("unshare"), None
        if exe:
            try:
                r = subprocess.run([exe, "-rn", sys.executable, "-c",
                                    _IFACES],
                                   capture_output=True, text=True, timeout=20)
                if r.returncode == 0 and r.stdout.strip() == "['lo']":
                    ok = [exe, "-rn"]
            except (OSError, subprocess.SubprocessError):
                pass
        _CACHE.append(ok)
    return _CACHE[0]


def jailed_argv(argv):
    """unshare -rn, then bring the namespace's own loopback up (still no route out), then exec."""
    prefix = unshare_prefix()
    if prefix is None:
        raise RuntimeError("NET_JAIL_UNAVAILABLE")
    return prefix + [sys.executable, str(Path(__file__).resolve()), "--lo-up-exec", *argv]


def _lo_up_exec(argv):
    import fcntl
    import socket
    import struct
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ifr = struct.pack("16sH", b"lo", 0)
        flags = struct.unpack("16sH", fcntl.ioctl(s, 0x8913, ifr)[:18])[1]   # SIOCGIFFLAGS
        fcntl.ioctl(s, 0x8914, struct.pack("16sH", b"lo", flags | 0x1))      # SIOCSIFFLAGS IFF_UP
    finally:
        s.close()
    if interfaces() != ["lo"]:
        sys.stderr.write("NET_JAIL_BROKEN: not an empty namespace\n")
        sys.exit(4)
    os.execvp(argv[0], argv)


def interfaces():
    with open("/proc/net/dev") as fh:
        return sorted(line.split(":")[0].strip() for line in fh.readlines()[2:])


def jailed_env(base=None):
    env = dict(os.environ if base is None else base)
    env["SPORTSEDGE_NET_JAILED"] = "1"
    return env


def main(args):
    if unshare_prefix() is None:
        sys.stderr.write("NET_JAIL_UNAVAILABLE: unshare -rn not permitted; not claiming isolation\n")
        return 3
    cmd = jailed_argv([sys.executable, "-m", "pytest", *(args or [str(GUARD)])])
    return subprocess.call(cmd, cwd=ROOT, env=jailed_env())


if __name__ == "__main__":
    if sys.argv[1:2] == ["--lo-up-exec"]:
        _lo_up_exec(sys.argv[2:])
    sys.exit(main(sys.argv[1:]))
