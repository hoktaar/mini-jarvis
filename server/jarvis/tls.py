"""HTTPS ohne Fremddienste: eigene kleine CA + Serverzertifikat für die PWA (Mikrofon!).

Die CA (`/data/tls/ca.crt`) wird einmal auf den Geräten installiert, danach vertrauen
Browser dem Jarvis-Zertifikat. Das Serverzertifikat wird automatisch erneuert, wenn es
bald abläuft oder neue Hostnamen/IPs dazukommen.
"""

from __future__ import annotations

import ipaddress
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from loguru import logger

SERVER_DAYS = 397          # Apple/Chrome-Limit für Serverzertifikate
CA_DAYS = 3650


def _write_key(path: Path, key) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)


def local_addresses() -> list[str]:
    names = {"localhost", socket.gethostname()}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            names.add(info[4][0])
    except OSError:
        pass
    try:   # Adresse der Standardroute (ohne Paket zu senden)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        names.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    names.add("127.0.0.1")
    return sorted(n for n in names if n and not n.startswith("fe80"))


def _san(hosts: list[str]) -> x509.SubjectAlternativeName:
    entries: list[x509.GeneralName] = []
    for h in sorted(set(hosts)):
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            entries.append(x509.DNSName(h))
    return x509.SubjectAlternativeName(entries)


def ensure_ca(tls_dir: Path):
    tls_dir.mkdir(parents=True, exist_ok=True)
    ca_key_path, ca_crt_path = tls_dir / "ca.key", tls_dir / "ca.crt"
    if ca_key_path.exists() and ca_crt_path.exists():
        key = serialization.load_pem_private_key(ca_key_path.read_bytes(), None)
        return key, x509.load_pem_x509_certificate(ca_crt_path.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mini-Jarvis lokale CA"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Mini-Jarvis")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_key(ca_key_path, key)
    ca_crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info(f"Eigene CA erzeugt: {ca_crt_path}")
    return key, cert


def ensure_server_cert(tls_dir: Path, hosts: list[str]) -> tuple[Path, Path]:
    """Serverzertifikat sicherstellen. Gibt (cert, key) zurück."""
    ca_key, ca_cert = ensure_ca(tls_dir)
    crt_path, key_path = tls_dir / "server.crt", tls_dir / "server.key"
    wanted = sorted(set(hosts) | set(local_addresses()))
    if crt_path.exists() and key_path.exists():
        cert = x509.load_pem_x509_certificate(crt_path.read_bytes())
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            have = {str(v) for v in san.get_values_for_type(x509.DNSName)} | \
                   {str(v) for v in san.get_values_for_type(x509.IPAddress)}
        except x509.ExtensionNotFound:
            have = set()
        fresh = cert.not_valid_after_utc - datetime.now(UTC) > timedelta(days=30)
        if fresh and set(wanted) <= have:
            return crt_path, key_path
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    cn = next((h for h in wanted if not h[0].isdigit() and h != "localhost"), "mini-jarvis")
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=SERVER_DAYS))
            .add_extension(_san(wanted), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_key(key_path, key)
    crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info(f"Serverzertifikat für {', '.join(wanted)} erzeugt")
    return crt_path, key_path


def cert_info(crt_path: Path) -> dict:
    if not crt_path.exists():
        return {}
    cert = x509.load_pem_x509_certificate(crt_path.read_bytes())
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(v) for v in san.get_values_for_type(x509.DNSName)] + \
                [str(v) for v in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        names = []
    return {"names": names, "expires": cert.not_valid_after_utc.isoformat(),
            "fingerprint": cert.fingerprint(hashes.SHA256()).hex(":").upper()}
