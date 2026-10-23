"""Session-wide network audit hook (t260, ruling 2026-10-23f).

sys.addaudithook fires inside C for socket.connect / socket.getaddrinfo / socket.sendto /
socket.bind / subprocess.Popen / os.posix_spawn / os.exec / os.spawn, so routes that reach
the unpatched C socket type (socket.socket.__bases__[0], _socket.socket.__mro__[1], a
reloaded socket module) are refused too. An audit hook cannot be removed, so it is installed
once per interpreter and gated by STATE.active; the guard test module supplies STATE.checker.
Not a sandbox: ctypes/raw syscalls never raise audit events (documented residual).
"""
import contextlib
import sys

_EVENTS = {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind",
           "subprocess.Popen", "os.posix_spawn", "os.exec", "os.spawn"}


class _State:
    installed = False
    active_depth = 0
    checker = None     # callable(event, args) -> raises to refuse

    @property
    def active(self):
        return self.active_depth > 0

    def hook(self, event, args):
        if self.active_depth <= 0 or event not in _EVENTS or self.checker is None:
            return
        self.active_depth -= 1          # no re-entry while checking
        try:
            self.checker(event, args)
        finally:
            self.active_depth += 1


STATE = _State()


def install():
    if not STATE.installed:
        sys.addaudithook(STATE.hook)
        STATE.installed = True
    return STATE


@contextlib.contextmanager
def active():
    install()
    STATE.active_depth += 1
    try:
        yield STATE
    finally:
        STATE.active_depth -= 1
