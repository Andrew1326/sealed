"""Self-signed certificates and fingerprints. Used by both the gateway (`sealed cert`) and, copied, the control plane."""
import datetime
import hashlib
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def make_self_signed(hosts: list, days: int = 825) -> tuple:
    """Returns (cert_pem, key_pem) for the given hostnames / IPs."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])])
    sans = []
    for h in hosts:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            sans.append(x509.DNSName(h))
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def fingerprint(cert_pem: bytes) -> str:
    cert = x509.load_pem_x509_certificate(cert_pem)
    return "sha256:" + hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def fingerprint_der(der: bytes) -> str:
    return "sha256:" + hashlib.sha256(der).hexdigest()


def write(out: Path, hosts: list, name: str = "tls") -> tuple:
    out.mkdir(parents=True, exist_ok=True)
    cert, key = make_self_signed(hosts)
    (out / f"{name}.crt").write_bytes(cert)
    (out / f"{name}.key").write_bytes(key)
    (out / f"{name}.key").chmod(0o600)
    return out / f"{name}.crt", out / f"{name}.key", fingerprint(cert)
