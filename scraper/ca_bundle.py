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
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID


def verifies(host: str, port: int, cafile: str) -> bool:
    ctx = ssl.create_default_context(cafile=cafile)
    try:
        with socket.create_connection((host, port), timeout=30) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return True
    except ssl.SSLCertVerificationError:
        return False


def chase_intermediates(host: str, port: int, max_depth: int = 4) -> list[str]:
    """Follow the AIA 'CA Issuers' links from the server certificate upwards."""
    pem = ssl.get_server_certificate((host, port), timeout=30)
    cert = x509.load_pem_x509_certificate(pem.encode())
    chain = []
    for _ in range(max_depth):
        if cert.issuer == cert.subject:  # reached a self-signed root
            break
        try:
            aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
        except x509.ExtensionNotFound:
            break
        urls = [d.access_location.value for d in aia
                if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS]
        if not urls:
            break
        with urllib.request.urlopen(urls[0], timeout=30) as resp:
            data = resp.read()
        try:
            issuer = x509.load_der_x509_certificate(data)
        except ValueError:
            issuer = x509.load_pem_x509_certificate(data)
        print(f"  downloaded intermediate: {issuer.subject.rfc4514_string()}  (from {urls[0]})")
        chain.append(issuer.public_bytes(Encoding.PEM).decode())
        cert = issuer
    return chain


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
        chain = chase_intermediates(host, port)
        out.write_text(roots.rstrip("\n") + "\n" + "".join(chain), encoding="utf-8")
        ok = verifies(host, port, str(out))
        print(f"{host}: verification with intermediates {'OK' if ok else 'STILL FAILING'}")
    except Exception as e:  # never block the scraper here; it will report its own error
        print(f"warning: could not prepare CA bundle for {host}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
