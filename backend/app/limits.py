"""Keys for rate limits that must not store personal data: network addresses and emails become keyed hashes.

The key is an HMAC with INROTATION_SECRET. Without it, a random key is made at each start, so counts
keyed by device or email start again after a restart (fine for development).
"""
import hmac
import ipaddress
import os
import secrets
from hashlib import sha256

from fastapi import Request

_process_secret = secrets.token_bytes(32)


def _digest(value: str) -> str:
    secret = os.environ.get("INROTATION_SECRET", "").encode() or _process_secret
    return hmac.new(secret, value.encode(), sha256).hexdigest()[:40]


def device_key(host: str | None) -> str | None:
    """A device is its network address. IPv6 counts by its /64, which is usually one home or phone."""
    if not host:
        return None
    try:
        ip = ipaddress.ip_address(host)
        net = str(ipaddress.ip_network(f"{ip}/64", strict=False)) if ip.version == 6 else str(ip)
    except ValueError:
        net = host
    return "d:" + _digest(net)


def email_key(email: str) -> str:
    return "e:" + _digest(email.strip().lower())


def client_host(request: Request) -> str | None:
    """The visitor's network address. Deployed (INROTATION_TRUST_PROXY=1), the API is only reachable through Caddy,
    which puts the real address in X-Real-IP (taken from Cloudflare's CF-Connecting-IP only for requests that really
    came through Cloudflare). Locally there's no proxy, so the connection's own address is used."""
    if os.environ.get("INROTATION_TRUST_PROXY") == "1" and request.headers.get("x-real-ip"):
        return request.headers["x-real-ip"]
    return request.client.host if request.client else None


def device_of(request: Request) -> str | None:
    return device_key(client_host(request))
