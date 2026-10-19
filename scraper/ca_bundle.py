"""
Build a CA bundle that lets Python verify CENACE's HTTPS certificate.

CENACE's server sends only its own certificate and omits the intermediate
certificate. Browsers download the missing intermediate automatically (via the
"Authority Information Access" URL inside the certificate); Python does not, so
requests fails with CERTIFICATE_VERIFY_FAILED. This script does what browsers do:
it reads that URL, downloads the intermediate(s) and writes certifi's trusted roots
+ those intermediates to one file. Verification stays fully ON — the chain must
still end in a trusted root CA.

Usage:  python scraper/ca_bundle.py www.cenace.gob.ec _work/ca-bundle.pem [--base roots.pem]
Then:   REQUESTS_CA_BUNDLE=_work/ca-bundle.pem python scraper/cenace.py
"""

from __future__ import annotations

import socket
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding, pkcs7
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID


def verifies(host: str, port: int, cafile: str) -> bool:
    ctx = ssl.create_default_context(cafile=cafile)
    try:
        with socket.create_connection((host, port), timeout=30) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return True
    except ssl.SSLCertVerificationError:
        return False


def load_certs(data: bytes) -> list:
    """AIA downloads come as DER, PEM or PKCS#7 (.p7c) — accept all of them."""
    for loader in (lambda d: [x509.load_der_x509_certificate(d)],
                   lambda d: x509.load_pem_x509_certificates(d),
                   lambda d: pkcs7.load_der_pkcs7_certificates(d),
                   lambda d: pkcs7.load_pem_pkcs7_certificates(d)):
        try:
            certs = loader(data)
            if certs:
                return certs
        except Exception:
            pass
    raise ValueError("unrecognised certificate format")


def chase_intermediates(host: str, port: int, max_depth: int = 4):
    """Follow the AIA 'CA Issuers' links from the server certificate upwards (yields PEM blocks)."""
    pem = ssl.get_server_certificate((host, port), timeout=30)
    cert = x509.load_pem_x509_certificate(pem.encode())
    for _ in range(max_depth):
        if cert.issuer == cert.subject:  # reached a self-signed root
            return
        try:
            aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
        except x509.ExtensionNotFound:
            return
        urls = [d.access_location.value for d in aia
                if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS]
        if not urls:
            return
        try:
            with urllib.request.urlopen(urls[0], timeout=30) as resp:
                certs = load_certs(resp.read())
        except Exception as e:
            print(f"  could not use {urls[0]}: {e}")
            return
        for c in certs:
            print(f"  downloaded intermediate: {c.subject.rfc4514_string()}  (from {urls[0]})")
        yield "".join(c.public_bytes(Encoding.PEM).decode() for c in certs)
        cert = certs[0]


def main(argv: list[str]) -> int:
    host, out = argv[1], Path(argv[2])
    base = argv[argv.index("--base") + 1] if "--base" in argv else certifi.where()
    port = 443
    out.parent.mkdir(parents=True, exist_ok=True)
    roots = Path(base).read_text(encoding="utf-8")
    out.write_text(roots, encoding="utf-8")
    try:
        if verifies(host, port, str(out)):
            print(f"{host}: certificate chain is complete, standard roots are enough.")
            return 0
        print(f"{host}: incomplete certificate chain, fetching intermediates…")
        bundle = roots.rstrip("\n") + "\n"
        for block in chase_intermediates(host, port):
            bundle += block
            out.write_text(bundle, encoding="utf-8")
            if verifies(host, port, str(out)):
                print(f"{host}: verification with intermediates OK")
                return 0
        print(f"{host}: verification still failing after adding intermediates")
    except Exception as e:  # never block the scraper here; it will report its own error
        print(f"warning: could not prepare CA bundle for {host}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
