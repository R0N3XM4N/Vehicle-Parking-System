import socket
import ssl
import sys
from datetime import datetime, timezone

HOST = sys.argv[1] if len(sys.argv) > 1 else "localhost"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def tls_connect(max_version=None, min_version=None):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if max_version:
        ctx.maximum_version = max_version
    if min_version:
        ctx.minimum_version = min_version
    with socket.create_connection((HOST, PORT), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname=HOST) as tls:
            req = f"GET /login HTTP/1.1\r\nHost: {HOST}\r\nConnection: close\r\n\r\n"
            tls.sendall(req.encode())
            body = tls.recv(4096)
            return tls.version(), tls.cipher(), tls.getpeercert(binary_form=True), body


try:
    version, cipher, cert, body = tls_connect()
    check("Server accepts TLS handshake", True, f"({version}, {cipher[0]})")
    check("Protocol is TLS 1.2 or newer", version in ("TLSv1.2", "TLSv1.3"), f"({version})")
    check("HTTP response is served over TLS", body.startswith(b"HTTP/1."), f"({body.split(b'\r\n')[0].decode(errors='replace')})")
except Exception as exc:
    check("Server accepts TLS handshake", False, f"({exc})")
    sys.exit(1)

for label, ver in (("TLS 1.0", ssl.TLSVersion.TLSv1), ("TLS 1.1", ssl.TLSVersion.TLSv1_1)):
    try:
        tls_connect(max_version=ver)
        check(f"Legacy {label} is rejected", False, "(connection succeeded)")
    except (ssl.SSLError, OSError):
        check(f"Legacy {label} is rejected", True)

try:
    with socket.create_connection((HOST, PORT), timeout=5) as raw:
        raw.sendall(f"GET /login HTTP/1.1\r\nHost: {HOST}\r\nConnection: close\r\n\r\n".encode())
        reply = raw.recv(4096)
    plain_ok = reply.startswith(b"HTTP/1.") and b" 200 " in reply.split(b"\r\n")[0]
    check("Plain HTTP is not served on the TLS port", not plain_ok)
except (ConnectionError, OSError, socket.timeout):
    check("Plain HTTP is not served on the TLS port", True, "(connection refused or closed)")

try:
    from cryptography import x509
    c = x509.load_der_x509_certificate(cert)
    expiry = c.not_valid_after_utc if hasattr(c, "not_valid_after_utc") else c.not_valid_after.replace(tzinfo=timezone.utc)
    check("Certificate is not expired", expiry > datetime.now(timezone.utc), f"(expires {expiry:%Y-%m-%d})")
except ImportError:
    print("[SKIP] certificate expiry check (pip install cryptography to enable)")

print("RESULT:", "PASS" if all(results) else "FAIL")
sys.exit(0 if all(results) else 1)
