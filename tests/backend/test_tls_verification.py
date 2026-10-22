"""Page fetches verify TLS certificates; an invalid one is reported, not silently trusted."""

import datetime
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from backend.config import settings
from backend.services.url_analyzer import URLAnalyzerService, get_verifying_first, is_certificate_error


@pytest.fixture
def self_signed_site(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_TARGETS", True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))

    class Page(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>Staging</title></head><body><button>Go</button></body></html>")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"https://localhost:{server.server_address[1]}/"
    server.shutdown()


async def test_an_invalid_certificate_is_still_fetched_but_flagged(self_signed_site):
    response, valid = await get_verifying_first(self_signed_site, timeout=5, headers={})
    assert response.status_code == 200
    assert valid is False


async def test_the_analyzer_reports_the_invalid_certificate(self_signed_site):
    result = await URLAnalyzerService.analyze_live_website(self_signed_site)
    assert result["page_title"] == "Staging"  # the page was still analyzed
    security = result["health_audit"]["security"]
    assert security["certificate_valid"] is False
    assert security["summary"] == "Invalid TLS certificate"
    assert security["score"] < 60  # no credit for HTTPS the browser would not trust


def test_certificate_errors_are_recognised_through_wrapping():
    wrapped = httpx.ConnectError("connect failed")
    wrapped.__cause__ = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed")
    assert is_certificate_error(wrapped)
    assert not is_certificate_error(httpx.ConnectError("Connection refused"))
