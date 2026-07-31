"""
Tor connection methods for networks where reaching the Tor network directly is
blocked (Iran, China, Russia, Turkmenistan …).

Four modes, in increasing order of censorship resistance:

  direct     Normal bootstrap straight to the guard relays. Fastest, and the
             only mode that needs nothing installed — but the relay IPs are
             public, so a censor can (and does) block them wholesale.
  vanilla    Plain bridge relays: ``UseBridges 1`` + ``Bridge <ip>:<port> <fp>``.
             Needs no helper binary. Defeats IP blocklists only — on the wire
             the handshake still looks like Tor, so DPI-based blocking sees it.
  obfs4      Bridges behind the obfs4 obfuscation layer, which makes the stream
             look like nothing in particular. Needs the ``lyrebird`` binary
             (the current name of what used to ship as ``obfs4proxy``).
  snowflake  WebRTC to volunteers' browsers, with the broker request fronted
             through a CDN. Gets through where obfs4 is already blocked, at the
             cost of speed. Needs the ``snowflake-client`` binary.

The built-in bridge lines below are the ones Tor Browser hands out through Moat
(``https://bridges.torproject.org/moat/circumvention/builtin``), captured on
2026-07-30. They are public and shared by every Tor Browser user, which cuts
both ways: censors know them too, so they get blocked and rotated over time.
That is why the settings UI always lets the user paste fresh lines — obtained
from https://bridges.torproject.org, from Telegram (@GetBridgesBot), or by
mailing bridges@torproject.org from a Gmail/Riseup address.

Nothing here talks to the network: assembling a config is pure string work, so
a blocked user can switch transports without first needing a working circuit.
"""

import shutil

MODE_DIRECT = "direct"
MODE_VANILLA = "vanilla"
MODE_OBFS4 = "obfs4"
MODE_SNOWFLAKE = "snowflake"

MODES: tuple[str, ...] = (MODE_DIRECT, MODE_VANILLA, MODE_OBFS4, MODE_SNOWFLAKE)

# Transport token each mode's bridge lines must start with. Vanilla bridge
# lines carry no token at all — they begin with the address.
_TRANSPORT_TOKEN: dict[str, str] = {
    MODE_OBFS4: "obfs4",
    MODE_SNOWFLAKE: "snowflake",
}

# Every transport token tor knows about, used to catch the common mistake of
# pasting obfs4 lines while "vanilla" is selected.
_KNOWN_TOKENS = (
    "obfs2", "obfs3", "obfs4", "scramblesuit", "meek", "meek_lite",
    "snowflake", "webtunnel", "conjure", "dnstt",
)

_BUILTIN_OBFS4: tuple[str, ...] = (
    "obfs4 37.218.245.14:38224 D9A82D2F9C2F65A18407B1D2B764F130847F8B5D cert=bjRaMrr1BRiAW8IE9U5z27fQaYgOhX1UCmOpg2pFpoMvo6ZgQMzLsaTzzQNTlm7hNcb+Sg iat-mode=0",
    "obfs4 51.222.13.177:80 5EDAC3B810E12B01F6FD8050D2FD3E277B289A08 cert=2uplIpLQ0q9+0qMFrK5pkaYRDOe460LL9WHBvatgkuRr/SL31wBOEupaMMJ6koRE6Ld0ew iat-mode=0",
    "obfs4 209.148.46.65:443 74FAD13168806246602538555B5521A0383A1875 cert=ssH+9rP8dG2NLDN2XuFw63hIO/9MNNinLmxQDpVa+7kTOa9/m+tGWT1SmSYpQ9uTBGa6Hw iat-mode=0",
    "obfs4 212.83.43.74:443 39562501228A4D5E27FCA4C0C81A01EE23AE3EE4 cert=PBwr+S8JTVZo6MPdHnkTwXJPILWADLqfMGoVvhZClMq/Urndyd42BwX9YFJHZnBB3H0XCw iat-mode=1",
    "obfs4 45.145.95.6:27015 C5B7CD6946FF10C5B3E89691A7D3F2C122D2117C cert=TD7PbUO0/0k6xYHMPW3vJxICfkMZNdkRrb63Zhl5j9dW3iRGiCx0A7mPhe5T2EDzQ35+Zw iat-mode=0",
    "obfs4 146.57.248.225:22 10A6CD36A537FCE513A322361547444B393989F0 cert=K1gDtDAIcUfeLqbstggjIw2rtgIKqdIhUlHp82XRqNSq/mtAjp1BIC9vHKJ2FAEpGssTPw iat-mode=0",
    "obfs4 212.83.43.95:443 BFE712113A72899AD685764B211FACD30FF52C31 cert=ayq0XzCwhpdysn5o0EyDUbmSOx3X/oTEbzDMvczHOdBJKlvIdHHLJGkZARtT4dcBFArPPg iat-mode=1",
)

_BUILTIN_SNOWFLAKE: tuple[str, ...] = (
    "snowflake 192.0.2.3:80 2B280B23E1107BB62ABFC40DDCC8824814F80A72 fingerprint=2B280B23E1107BB62ABFC40DDCC8824814F80A72 url=https://1098762253.rsc.cdn77.org/ fronts=app.datapacket.com,www.datapacket.com ice=stun:stun.epygi.com:3478,stun:stun.uls.co.za:3478,stun:stun.voipgate.com:3478,stun:stun.mixvoip.com:3478,stun:stun.telnyx.com:3478,stun:stun.hot-chilli.net:3478,stun:stun.fitauto.ru:3478,stun:stun.m-online.net:3478 utls-imitate=hellorandomizedalpn",
    "snowflake 192.0.2.4:80 8838024498816A039FCBBAB14E6F40A0843051FA fingerprint=8838024498816A039FCBBAB14E6F40A0843051FA url=https://1098762253.rsc.cdn77.org/ fronts=app.datapacket.com,www.datapacket.com ice=stun:stun.epygi.com:3478,stun:stun.uls.co.za:3478,stun:stun.voipgate.com:3478,stun:stun.mixvoip.com:3478,stun:stun.telnyx.com:3478,stun:stun.hot-chilli.net:3478,stun:stun.fitauto.ru:3478,stun:stun.m-online.net:3478 utls-imitate=hellorandomizedalpn",
)

BUILTIN_BRIDGES: dict[str, tuple[str, ...]] = {
    # Tor Browser ships no default vanilla bridges (an unobfuscated bridge only
    # stays useful while its address is unpublished), so this mode always needs
    # lines from the user.
    MODE_VANILLA: (),
    MODE_OBFS4: _BUILTIN_OBFS4,
    MODE_SNOWFLAKE: _BUILTIN_SNOWFLAKE,
}

# Candidate executables per mode, in preference order.
TRANSPORT_BINARIES: dict[str, tuple[str, ...]] = {
    MODE_OBFS4: ("lyrebird", "obfs4proxy"),
    MODE_SNOWFLAKE: ("snowflake-client",),
}

# Shown verbatim next to a "not installed" warning; package names, so not
# translated.
INSTALL_HINTS: dict[str, str] = {
    MODE_OBFS4: "Arch: obfs4proxy · Debian/Ubuntu: obfs4proxy · Fedora: obfs4",
    MODE_SNOWFLAKE: "Arch: snowflake (AUR) · Debian/Ubuntu: snowflake-client",
}


class BridgeConfigError(RuntimeError):
    """The selected connection method cannot be assembled.

    Raised instead of quietly falling back to a direct connection: on a network
    that filters Tor, an unannounced direct bootstrap is exactly the traffic the
    user picked a bridge to avoid emitting.
    """


def normalize_mode(mode: str | None) -> str:
    return mode if mode in MODES else MODE_DIRECT


def uses_bridges(mode: str | None) -> bool:
    return normalize_mode(mode) != MODE_DIRECT


def needs_transport_binary(mode: str | None) -> bool:
    return normalize_mode(mode) in TRANSPORT_BINARIES


def find_transport_binary(mode: str | None) -> str | None:
    """Absolute path of the pluggable-transport binary for `mode`, if present."""
    for name in TRANSPORT_BINARIES.get(normalize_mode(mode), ()):
        path = shutil.which(name)
        if path:
            return path
    return None


def transport_binary_names(mode: str | None) -> str:
    """Human-readable list of the binaries that satisfy `mode` ("a or b")."""
    return " / ".join(TRANSPORT_BINARIES.get(normalize_mode(mode), ()))


def parse_bridge_lines(text: str) -> list[str]:
    """Split a textarea's worth of bridge lines into normalized entries.

    Tolerates what people actually paste: a leading ``Bridge`` keyword copied
    out of a torrc, ``#`` comments, blank lines and stray whitespace.
    """
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith("bridge "):
            line = line[len("bridge "):].strip()
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return lines


def effective_bridge_lines(mode: str, custom_text: str) -> list[str]:
    """Lines that would actually be used: the user's if any, else the built-ins."""
    custom = parse_bridge_lines(custom_text)
    if custom:
        return custom
    return list(BUILTIN_BRIDGES.get(normalize_mode(mode), ()))


def _validate(mode: str, lines: list[str]) -> None:
    token = _TRANSPORT_TOKEN.get(mode)
    for line in lines:
        first = line.split(" ", 1)[0].lower()
        if token:
            if first != token:
                raise BridgeConfigError(
                    f"This bridge line is not an {token} line: {line[:48]}…"
                )
        elif first in _KNOWN_TOKENS:
            raise BridgeConfigError(
                f"This is a {first} bridge line — select the {first} "
                f"connection method to use it."
            )


def torrc_options(mode: str, custom_text: str = "") -> dict[str, str | list[str]]:
    """Assemble the torrc fragment for `mode`.

    Returns an empty dict for a direct connection. Raises `BridgeConfigError`
    when the mode is unusable (no bridge lines, or a missing transport binary)
    so the caller can refuse to start Tor rather than silently connecting
    directly.
    """
    mode = normalize_mode(mode)
    if mode == MODE_DIRECT:
        return {}

    lines = effective_bridge_lines(mode, custom_text)
    if not lines:
        raise BridgeConfigError("No bridge lines configured.")
    _validate(mode, lines)

    options: dict[str, str | list[str]] = {"UseBridges": "1"}

    if mode in TRANSPORT_BINARIES:
        binary = find_transport_binary(mode)
        if not binary:
            raise BridgeConfigError(
                f"{transport_binary_names(mode)} is not installed "
                f"({INSTALL_HINTS.get(mode, '')})."
            )
        options["ClientTransportPlugin"] = f"{_TRANSPORT_TOKEN[mode]} exec {binary}"

    options["Bridge"] = lines
    return options
