"""SSRF defence for the HTTP connector (ThreatModel.md §3⑥: "Deny-list of
link-local, loopback, and private ranges; DNS re-resolution guard against
rebinding").

Two checks, and both matter:

1. **Every address a hostname resolves to is checked against the deny-list**,
   not just the first one — a hostname that resolves to one public and one
   internal address must still be refused, since nothing stops a client from
   picking the internal one.
2. **The connection is pinned to the address that was checked.** Resolving,
   validating, and then handing the *hostname* to the HTTP client re-resolves
   it a second time at connect — and DNS can answer differently the second
   time (a rebinding attack, or just a round-robin record). `resolve_and_pin`
   substitutes the verified IP into the request URL and carries the original
   hostname through as the `Host` header and the TLS SNI value, so the
   connection that is actually opened is the one that was checked.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Collection

import anyio
import httpx

from mnemos.core.errors import SsrfRejectedError, ValidationError

#: Beyond the RFC1918/loopback/link-local basics, this also covers
#: CGNAT (100.64.0.0/10 — some cloud metadata endpoints sit behind it),
#: "this network" (0.0.0.0/8), and multicast — none of them are a
#: legitimate target for an operator-curated document URL.
_DENIED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "224.0.0.0/4",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)


def _is_denied(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or any(address in network for network in _DENIED_NETWORKS)
    )


def _resolve_sync(host: str, port: int) -> set[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return {str(info[4][0]) for info in infos}


async def resolve_and_pin(
    url: str, *, allowed_private_hosts: Collection[str] = ()
) -> tuple[httpx.URL, str]:
    """Validate `url`'s host and return a request URL pinned to a checked
    address, plus the original hostname (for the `Host` header and SNI).

    Raises `SsrfRejectedError` if the host itself, or any address it resolves
    to, falls inside the deny-list and the deployment operator has not named
    that exact host in ``allowed_private_hosts``; `ValidationError` for anything
    that is not a plain `http(s)://host[:port]/...` URL (embedded
    credentials are refused outright — `http://user:pass@host` is a classic
    way to smuggle a second, differently-parsed hostname past a naive check).
    """
    parsed = httpx.URL(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError(f"connector URL must be http(s), got {parsed.scheme!r}", url=url)
    if parsed.username or parsed.password:
        raise ValidationError("connector URL must not carry embedded credentials", url=url)
    if not parsed.host:
        raise ValidationError("connector URL has no host", url=url)

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await anyio.to_thread.run_sync(_resolve_sync, parsed.host, port)
    except OSError as exc:
        raise ValidationError(f"could not resolve host {parsed.host!r}", url=url) from exc
    if not addresses:
        raise ValidationError(f"host {parsed.host!r} resolved to no address", url=url)

    private_host_allowed = parsed.host.casefold() in {
        host.casefold() for host in allowed_private_hosts
    }
    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if _is_denied(ip) and not private_host_allowed:
            raise SsrfRejectedError(
                f"{parsed.host!r} resolves to a denied address range",
                url=url,
                host=parsed.host,
                address=str(ip),
            )

    pinned = parsed.copy_with(host=next(iter(addresses)))
    return pinned, parsed.host
