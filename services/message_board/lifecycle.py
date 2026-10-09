"""Loopback checks and capability-based local service shutdown."""
from __future__ import annotations

import asyncio
import errno
import ipaddress
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx

from .runtime_records import RecordError, read_record

DEFAULT_URL = "http://127.0.0.1:8765"


@dataclass
class ShutdownControl:
    instance_id: str
    capability: str
    callback: Callable[[], None]


def is_loopback_host(host: str, *, allow_localhost: bool = True) -> bool:
    if allow_localhost and host.lower().rstrip(".") == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


def check_bind(host: str, token: str | None) -> None:
    if not is_loopback_host(host) and not token:
        raise SystemExit("non-loopback message board binds require a bearer token")


def _local_port(url: str) -> int:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not is_loopback_host(parsed.hostname or ""):
        raise RecordError("stop requires an http URL on a loopback host")
    if any((parsed.username, parsed.password, parsed.query, parsed.fragment)):
        raise RecordError("stop URL must not contain credentials, query or fragment")
    if parsed.path not in ("", "/"):
        raise RecordError("stop URL must point to the board root")
    return parsed.port or 80


def _connection_refused(error: BaseException) -> bool:
    """Only a real refused connection authorizes an already-down result."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, ConnectionRefusedError):
            return True
        if isinstance(error, OSError) and error.errno in (errno.ECONNREFUSED, 10061):
            return True
        if getattr(error, "winerror", None) in (10061, 1225):
            return True
        error = error.__cause__ or error.__context__
    return False


async def _health(client, url: str) -> dict:
    async with asyncio.timeout(3.0):
        response = await client.get(url.rstrip("/") + "/health",
                                    follow_redirects=False, timeout=3.0)
    if response.status_code != 200:
        raise RecordError("board health request failed or redirected")
    body = response.json()
    if not isinstance(body, dict):
        raise RecordError("foreign or malformed board health response")
    expected = {"status": "ok", "version": 1}
    if any(body.get(key) != value for key, value in expected.items()):
        raise RecordError("foreign or malformed board health response")
    _validate_health_identity(body)
    return body


def _validate_health_identity(body: dict) -> None:
    valid_pid = type(body.get("pid")) is int and body["pid"] > 0
    instance = body.get("instance_id")
    valid_instance = isinstance(instance, str) and re.fullmatch(r"[0-9a-f]{32}", instance)
    if type(body["version"]) is not int or not valid_pid or not valid_instance:
        raise RecordError("foreign or malformed board health response")


def _matching_record(runtime_dir: Path, port: int, health: dict) -> dict:
    record = read_record(runtime_dir, port)
    if record.get("port") != port or _local_port(record.get("url", "")) != port:
        raise RecordError("local runtime record has a different port")
    if record.get("instance_id") != health["instance_id"]:
        raise RecordError("local runtime record is stale")
    capability = record.get("capability", "")
    if not isinstance(capability, str) or not re.fullmatch(r"[0-9a-f]{64}", capability):
        raise RecordError("local runtime record has an invalid shutdown capability")
    return record


async def _poll_stopped(client, url: str, instance_id: str, wait_s: float) -> int:
    try:
        async with asyncio.timeout(wait_s):
            while True:
                try:
                    if (await _health(client, url))["instance_id"] != instance_id:
                        return 0
                except httpx.ConnectError as error:
                    if _connection_refused(error):
                        return 0
                except (httpx.HTTPError, RecordError, ValueError, TimeoutError):
                    pass  # retry transient closures until the wall-clock deadline
                await asyncio.sleep(0.1)
    except TimeoutError as error:
        raise RecordError("board shutdown was not confirmed before the deadline") from error


async def _stop_request(url: str, runtime_dir: Path, client, wait_s: float) -> int:
    port = _local_port(url)
    try:
        health = await _health(client, url)
    except httpx.ConnectError as error:
        if _connection_refused(error):
            return 0
        raise
    record = _matching_record(runtime_dir, port, health)
    headers = {"X-Dagi-Stop-Token": record["capability"]}
    from .settings import resolve_token  # settings imports this module

    token = resolve_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with asyncio.timeout(3.0):
        response = await client.post(url.rstrip("/") + "/shutdown", headers=headers,
                                     json={"instance_id": health["instance_id"]},
                                     follow_redirects=False, timeout=3.0)
    if response.status_code != 202 or response.json() != {"status": "stopping"}:
        raise RecordError("board refused shutdown; check bearer token and local runtime record")
    return await _poll_stopped(client, url, health["instance_id"], wait_s)


async def _run_stop(url: str, runtime_dir: Path, client, wait_s: float) -> int:
    if client is not None:
        return await _stop_request(url, runtime_dir, client, wait_s)
    async with httpx.AsyncClient(trust_env=False) as owned:
        return await _stop_request(url, runtime_dir, owned, wait_s)


def stop_local(url: str, *, runtime_dir: Path, client=None, wait_s: float = 5.0) -> int:
    """Synchronous CLI entry; injected clients must implement AsyncClient's interface."""
    try:
        return asyncio.run(_run_stop(url, runtime_dir, client, wait_s))
    except (httpx.HTTPError, OSError, ValueError, TypeError, RecordError) as error:
        reason = str(error) or "board request timed out"
        print(f"Cannot stop message board: {reason}", file=sys.stderr)
        return 1
