"""
STP provider product identity from the registration ``server`` field (D15).

The Stimma Tools Protocol registration carries a ``server`` field — a fixed
``Name/Version`` software identifier set by the provider software (not the
user), designated by the spec for telemetry and debugging. This module
validates it into ``{productName, productVersion}``:

- ``productName``: the name part when it matches a known product pattern,
  else ``other``. Never a user-entered label.
- ``productVersion``: the version part when it is version-shaped
  (dotted digits with an optional ``-suffix``), else absent.

Returns ``{"productName": "unknown"}`` when the field is missing/unparseable.
"""
import re
from typing import Optional, TypedDict


class ProductIdentity(TypedDict, total=False):
    productName: str
    productVersion: str


# Known STP server product names (closed list; grows via the normal catalog
# process). Matching is case-insensitive on the exact name part.
KNOWN_PRODUCTS = {
    "comfyui-stimma": "ComfyUI-Stimma",
    "stimma-tools": "stimma-tools",
    "stimma-cloud": "stimma-cloud",
}

# Name/Version with a version that is dotted digits + optional -suffix
# (e.g. "ComfyUI-Stimma/1.1.0", "MyServer/2.0.1-beta.2").
_SERVER_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)/(\S+)\s*$")
_VERSION_RE = re.compile(r"^\d+(\.\d+)*(-[A-Za-z0-9.]+)?$")


def parse_server_identity(server: Optional[str]) -> ProductIdentity:
    """Validate an STP ``server`` field into product identity."""
    if not server or not isinstance(server, str):
        return {"productName": "unknown"}

    match = _SERVER_RE.match(server)
    if not match:
        return {"productName": "unknown"}

    raw_name, raw_version = match.group(1), match.group(2)
    product_name = KNOWN_PRODUCTS.get(raw_name.lower(), "other")

    identity: ProductIdentity = {"productName": product_name}
    if _VERSION_RE.match(raw_version):
        identity["productVersion"] = raw_version
    return identity
