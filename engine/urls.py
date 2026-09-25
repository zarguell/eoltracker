"""One safe-URL rule for every URL the catalog stores, prints or publishes.

Upstream APIs, vendor tables and contributor citations all hand this project
strings that end up as ``href`` values, iCalendar ``URL`` properties and
provenance fields. A string that is not an absolute public ``http(s)`` URL is
not a link: ``javascript:``/``data:`` execute or smuggle content when a reader
clicks them, ``file:`` reads the viewer's disk, and a ``user:token@host`` or a
signed query string leaks a credential into CI logs and the published catalog
the moment it is echoed back in an error message or written to a record.

The rule lives here once so ingestion, validation, publication and the site all
apply the same one, and a fix to it is a fix everywhere. Nothing in this module
imports the rest of ``engine``: it is a leaf, so any module may import it
without creating a cycle, and its verdict never depends on the network.

Two calls deliberately differ in strictness, because two different callers need
different things:

* ``safe_http_url(value, field, allow_fragment=...)`` — the admission check. It
  fails closed and returns the value unchanged; a persistence path that can
  refuse uses this.
* ``safe_http_url_or_none(value)`` — the presentation check. A renderer must
  never turn a bad upstream value into a live link, but it must not abort a
  build over one either, so this drops instead of raising.

Fragments are the one place the two shapes of citation genuinely differ: an
importer stores a vendor's own deep link verbatim (``...#release-history`` is a
real citation), while a *fetched* research citation is a page whose anchor names
no section the fetch returns, so the contribution path refuses one.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

# The only schemes a published link may carry.
SCHEMES = ("http", "https")
# Schemes a *citation* may carry. A citation is refetched and republished as
# provenance, so it must be the public web's own transport: an ``http://``
# citation is neither authenticatable nor stable, and the whole point of #102 is
# that a stored citation is a public, verifiable page.
CITATION_SCHEMES = ("https",)
# Host suffixes that never name a public page. ``.localhost`` and ``.home.arpa``
# are reserved, ``.local`` is mDNS, and ``.internal`` is a private convention; a
# citation served from one of these is either an internal note or an SSRF probe.
_PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")

# Query parameters that name a credential. A citation URL that needs one is not
# a public citation, so the presence of such a key refuses the URL rather than
# storing a secret. Matched on the normalized key (case folded, ``-``/``.``
# folded to ``_``) so ``X-Amz-Signature`` and ``api.key`` are both caught.
_CREDENTIAL_KEYS = frozenset({
    "access_key", "access_key_id", "access_token", "api_key", "apikey", "auth",
    "authorization", "awsaccesskeyid", "client_secret", "credential",
    "credentials", "id_token", "jwt", "key", "password", "passwd", "pwd",
    "sas", "secret", "session", "session_id", "session_token", "sig",
    "signature", "signed", "sso_token", "subscription_key", "token",
    "x_amz_credential", "x_amz_security_token", "x_amz_signature",
})
# A query key that *contains* one of these is credential-shaped too: signed
# URLs name their parameters with prefixes and suffixes (``X-Goog-Signature``,
# ``sig_expires``, ``SharedAccessSignature``).
_CREDENTIAL_MARKERS = ("signature", "credential", "accesskey", "accesstoken",
                       "apikey", "authtoken", "sessiontoken", "sastoken",
                       "subscriptionkey", "sharedaccess", "secret", "password",
                       "passwd", "bearer")
# Percent-encoded CR, LF and NUL: a value carrying one of these can split an
# HTTP header or a rendered attribute when a downstream consumer decodes it.
_ENCODED_UNSAFE = ("%00", "%0a", "%0d")


def _control_free(value, field):
    """Refuse control characters and whitespace, raw or percent-encoded."""
    for character in value:
        if ord(character) < 0x20 or ord(character) == 0x7F:
            raise ValueError(f"{field} must not contain control characters")
        if character.isspace():
            raise ValueError(f"{field} must not contain whitespace: {redact_url(value)!r}")
    lowered = value.lower()
    for encoded in _ENCODED_UNSAFE:
        if encoded in lowered:
            raise ValueError(f"{field} must not contain encoded control characters: "
                             f"{redact_url(value)!r}")


def credential_key(key):
    """True when a query parameter name is credential-shaped."""
    folded = str(key).strip().lower().replace("-", "_").replace(".", "_").replace(" ", "_")
    if folded in _CREDENTIAL_KEYS:
        return True
    compact = folded.replace("_", "")
    return any(marker in compact for marker in _CREDENTIAL_MARKERS)


def redact_url(value):
    """A URL with its userinfo, query and fragment removed, for logs and errors.

    Every refusal message prints through this, so a rejected credential-bearing
    citation never round-trips its secret back out through a CI log or a
    validation report. A value that cannot be parsed is reported as its scheme
    and host only, or as a placeholder when even that is absent.
    """
    if not isinstance(value, str):
        return "<not a string>"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<unparseable url>"
    if not parsed.hostname:
        return quote(parsed.scheme or "<no scheme>", safe=":") + ":<redacted>"
    authority = _authority(parsed)
    return urlunsplit((parsed.scheme, authority, parsed.path or "", "", ""))


def _authority(parsed):
    """``host[:port]`` of a parsed URL, without any userinfo it carried."""
    try:
        port = parsed.port
    except ValueError:
        return parsed.hostname
    return parsed.hostname if port is None else f"{parsed.hostname}:{port}"


def public_host(host):
    """Refuse a host that cannot name a page on the public web, or return ``None``.

    A single label is not a public name (``intranet`` resolves only through a
    private resolver), the reserved suffixes never leave the local network, and a
    private, loopback, link-local or otherwise non-global IP literal is not a
    public citation. The check is on the *literal* host only: resolution happens
    at fetch time and is out of scope for a string rule.
    """
    if not isinstance(host, str):
        return "the URL names no host"
    name = host.strip().lower().rstrip(".")
    if not name:
        return "the URL names no host"
    if name == "localhost" or name.endswith(_PRIVATE_SUFFIXES):
        return f"{name!r} is a local name, not a public host"
    if "." not in name:
        return f"{name!r} is a single label, not a public host"
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return None
    if not address.is_global:
        return f"{name} is not a globally routable address"
    return None


def safe_http_url(value, field="url", allow_fragment=True):
    """Return ``value`` when it is a safe absolute public http(s) URL, else raise.

    Fails closed: anything that is not a plain ``http``/``https`` URL with a
    host, no userinfo, no control or whitespace characters and no
    credential-shaped query key raises ``ValueError``; so does a fragment when
    the caller passes ``allow_fragment=False``. The value is returned unchanged
    — this is an admission check, not a normalizer, so a stored URL keeps the
    bytes the source published. Refusal messages carry the redacted form, never
    the secret they refused.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an absolute http(s) URL, not {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{field} must be a non-empty absolute http(s) URL")
    if value != value.strip():
        raise ValueError(f"{field} must not be padded with whitespace: {redact_url(value)!r}")
    _control_free(value, field)
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise ValueError(f"{field} is not a parseable URL: {redact_url(value)!r}") from error
    if parsed.scheme.lower() not in SCHEMES:
        raise ValueError(f"{field} must use the http or https scheme: {redact_url(value)!r}")
    if not parsed.netloc:
        raise ValueError(f"{field} must be an absolute http(s) URL with a host: "
                         f"{redact_url(value)!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field} must not carry credentials in its authority: "
                         f"{redact_url(value)!r}")
    if not parsed.hostname:
        raise ValueError(f"{field} must name a host: {redact_url(value)!r}")
    if parsed.fragment and not allow_fragment:
        raise ValueError(f"{field} must not carry a fragment: {redact_url(value)!r}")
    if parsed.query:
        try:
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
        except ValueError as error:
            raise ValueError(f"{field} has an unparseable query string: "
                             f"{redact_url(value)!r}") from error
        for key, _ in pairs:
            if credential_key(key):
                raise ValueError(f"{field} carries a credential or token query parameter "
                                 f"({key!r}); a citation must be a public URL: "
                                 f"{redact_url(value)!r}")
    return value


def safe_http_url_or_none(value):
    """``safe_http_url`` for presentation sinks: the URL, or ``None`` when unsafe.

    A renderer must never turn a bad upstream value into a live link, but it
    also must not fail a whole build over one, so this is the non-raising form.
    It is deliberately separate from ``safe_http_url``: a persistence path that
    can refuse should refuse loudly, and only the sink that cannot abort uses
    this.
    """
    try:
        return safe_http_url(value)
    except ValueError:
        return None


def safe_citation_url(value, field="source_url"):
    """Return ``value`` when it is a safe *public citation* URL, else raise.

    A citation is stricter than a published link (#102): it is refetched at
    admission and republished verbatim as provenance, so it must be an
    ``https`` page on a public host with no fragment and no credential-bearing
    query parameter. Each refusal names the reason and prints the redacted URL,
    never the secret it refused, so a credential cannot round-trip into a CI log
    or a validation report through the error message.
    """
    value = safe_http_url(value, field, allow_fragment=False)
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in CITATION_SCHEMES:
        raise ValueError(f"{field} must use the https scheme; a citation is a public, "
                         f"authenticatable page: {redact_url(value)!r}")
    problem = public_host(parsed.hostname)
    if problem:
        raise ValueError(f"{field} {problem}: {redact_url(value)!r}")
    return value
