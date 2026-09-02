"""Serving-device identity: stable device id and a self-signed TLS keypair.

Both are minted once, on the first serve, and then persisted in config so the
account registry can key on the device across restarts and connecting clients
can pin the certificate.

Self-signed is deliberate and sufficient here. The connecting side never asks
a CA whether to trust this cert; it compares the SHA-256 of the DER against a
fingerprint it read from the per-account device registry over an authenticated
channel. That is real pinning, not trust-on-first-use, and it means a LAN
attacker who intercepts the connection cannot present a substitute cert.
"""
from __future__ import annotations

import datetime
import hashlib
import ipaddress
import secrets
import socket
from typing import Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from core.logging import get_logger

log = get_logger(__name__)

# Long enough that expiry is not an operational concern for a LAN service
# whose trust comes from pinning rather than validity dates.
CERT_VALIDITY_DAYS = 3650


def generate_device_id() -> str:
    """URL-safe id, matching the registry's 8-64 char contract."""
    return secrets.token_urlsafe(24)


def default_device_name() -> str:
    try:
        name = socket.gethostname().split(".")[0]
    except Exception:
        name = ""
    return name or "Unnamed server"


def local_addresses() -> list[str]:
    """Non-loopback IPv4 addresses this host can be reached at.

    Tailscale addresses live in 100.64.0.0/10 (CGNAT), which is how they are
    told apart from ordinary LAN addresses without shelling out to tailscale.
    """
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if addr not in found and not addr.startswith("127."):
                found.append(addr)
    except Exception:
        pass

    # getaddrinfo misses interfaces on many Linux setups; ask the routing
    # table which source address would be used to reach the outside world.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1, never actually routed
            addr = s.getsockname()[0]
            if addr and not addr.startswith("127.") and addr not in found:
                found.append(addr)
    except Exception:
        pass

    return found


def is_tailscale_address(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def cert_fingerprint(cert_pem: str) -> str:
    """SHA-256 of the certificate DER, lowercase hex — what the client pins."""
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def generate_self_signed_cert(device_name: str, addresses: list[str]) -> Tuple[str, str]:
    """Return (cert_pem, key_pem) for this device.

    Every known address goes in the SAN so that TLS hostname checks pass on
    whichever route the client picks. P-256 rather than RSA: much faster to
    generate, and the handshake is on the critical path of every app launch.
    """
    key = ec.generate_private_key(ec.SECP256R1())

    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, device_name[:64] or "stimma")])

    sans: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for addr in addresses:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(addr)))
        except ValueError:
            sans.append(x509.DNSName(addr))
    sans.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return cert_pem, key_pem


def ensure_identity(settings_multi_device) -> Tuple[str, str, str, str]:
    """Mint anything missing, returning (device_id, name, cert_pem, key_pem).

    Caller is responsible for persisting: this is pure so it can be tested
    without touching config on disk.
    """
    device_id = settings_multi_device.device_id or generate_device_id()
    name = settings_multi_device.device_name or default_device_name()
    cert_pem = settings_multi_device.cert_pem
    key_pem = settings_multi_device.key_pem

    if not cert_pem or not key_pem:
        cert_pem, key_pem = generate_self_signed_cert(name, local_addresses())
        log.info("multi-device: generated self-signed identity", device_id=device_id)

    return device_id, name, cert_pem, key_pem
