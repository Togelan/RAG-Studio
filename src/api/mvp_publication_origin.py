"""Canonical exact-origin policy for the Personal Lab publication boundary."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, NewType
from urllib.parse import urlsplit

CanonicalOrigin = NewType("CanonicalOrigin", str)

_HOST_PATTERN: Final = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*"
)


class OriginRejection(StrEnum):
    """Stable rejection categories that do not echo attacker-controlled input."""

    MISSING = "missing"
    NULL = "null"
    WILDCARD = "wildcard"
    SCHEME = "scheme"
    CREDENTIALS = "credentials"
    NON_ORIGIN_COMPONENT = "non_origin_component"
    LOCALHOST = "localhost"
    IPV6 = "ipv6"
    MALFORMED = "malformed"


class RequestKind(StrEnum):
    """Public HTTP flows governed by the same exact-origin rule."""

    REQUEST = "request"
    PREFLIGHT = "preflight"


@dataclass(frozen=True, slots=True)
class OriginRejectedError(ValueError):
    """Reject one untrusted origin without retaining or rendering its value."""

    reason: OriginRejection

    def __str__(self) -> str:
        return f"Origin rejected: {self.reason.value}."


def canonicalize_origin(raw_origin: str | None) -> CanonicalOrigin:
    """Parse one HTTP origin and normalize only case and its default port."""
    if raw_origin is None or raw_origin == "":
        raise OriginRejectedError(OriginRejection.MISSING)
    if raw_origin == "null":
        raise OriginRejectedError(OriginRejection.NULL)
    if "*" in raw_origin:
        raise OriginRejectedError(OriginRejection.WILDCARD)
    if raw_origin != raw_origin.strip() or any(char.isspace() for char in raw_origin):
        raise OriginRejectedError(OriginRejection.MALFORMED)
    try:
        parsed = urlsplit(raw_origin)
        port = parsed.port
    except ValueError:
        raise OriginRejectedError(OriginRejection.MALFORMED) from None
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise OriginRejectedError(OriginRejection.SCHEME)
    if parsed.username is not None or parsed.password is not None:
        raise OriginRejectedError(OriginRejection.CREDENTIALS)
    if parsed.path or parsed.query or parsed.fragment:
        raise OriginRejectedError(OriginRejection.NON_ORIGIN_COMPONENT)
    hostname = parsed.hostname
    if hostname is None or not hostname.isascii():
        raise OriginRejectedError(OriginRejection.MALFORMED)
    hostname = hostname.lower()
    if ":" in hostname:
        raise OriginRejectedError(OriginRejection.IPV6)
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise OriginRejectedError(OriginRejection.LOCALHOST)
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            legacy_address = ipaddress.IPv4Address(socket.inet_aton(hostname))
        except OSError:
            legacy_address = None
        if legacy_address is not None:
            reason = (
                OriginRejection.LOCALHOST
                if legacy_address.is_loopback
                else OriginRejection.MALFORMED
            )
            raise OriginRejectedError(reason) from None
        if _HOST_PATTERN.fullmatch(hostname) is None:
            raise OriginRejectedError(OriginRejection.MALFORMED) from None
    else:
        if address.version == 6:
            raise OriginRejectedError(OriginRejection.IPV6)
        if address.is_loopback:
            raise OriginRejectedError(OriginRejection.LOCALHOST)
    canonical_port = None if (scheme, port) in {("http", 80), ("https", 443)} else port
    suffix = "" if canonical_port is None else f":{canonical_port}"
    return CanonicalOrigin(f"{scheme}://{hostname}{suffix}")
