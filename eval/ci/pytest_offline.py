"""Pytest plugin for CI: no internet, and a test that reaches for it is skipped, not failed or deleted.

    PYTHONPATH=eval/ci python -m pytest -p pytest_offline <tests>

- Any connection to a host other than this machine skips the test that made it, with the host in the reason.
- @pytest.mark.network skips a test up front, for tests that need the internet and say so.
- The summary lists every test skipped for the network, so the list is visible on every run.
Loopback stays open, so a test may start a local server.
"""
import ipaddress
import socket

import pytest

_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", ""}
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo
_skipped = []


def _is_local(host):
    if host is None:
        return True
    host = host.decode() if isinstance(host, bytes) else str(host)
    if host.lower() in _LOCAL_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
        return ip.is_loopback or ip.is_unspecified
    except ValueError:
        return False


def _refuse(host):
    pytest.skip(f"needs the network ({host}); skipped offline", allow_module_level=True)


def _getaddrinfo(host, *a, **kw):
    if not _is_local(host):
        _refuse(host)
    return _real_getaddrinfo(host, *a, **kw)


def _connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
        _refuse(address[0])
    return _real_connect(self, address)


def _connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
        _refuse(address[0])
    return _real_connect_ex(self, address)


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs the internet; skipped by the offline plugin")
    socket.getaddrinfo = _getaddrinfo
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex


def pytest_unconfigure(config):
    socket.getaddrinfo = _real_getaddrinfo
    socket.socket.connect = _real_connect
    socket.socket.connect_ex = _real_connect_ex


def pytest_collection_modifyitems(config, items):
    for item in items:
        if item.get_closest_marker("network"):
            item.add_marker(pytest.mark.skip(reason="marked network; skipped offline"))


def pytest_runtest_logreport(report):
    if report.skipped and "offline" in str(report.longrepr):
        _skipped.append(report.nodeid)


def pytest_terminal_summary(terminalreporter):
    terminalreporter.section("offline")
    if _skipped:
        terminalreporter.write_line(f"{len(_skipped)} test(s) skipped because they need the network:")
        for nodeid in _skipped:
            terminalreporter.write_line(f"  {nodeid}")
    else:
        terminalreporter.write_line("no test reached for the network")
