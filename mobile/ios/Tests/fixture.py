"""Disposable loopback TLS fixture; never contacts an account or real backend."""
import base64
import hashlib
import gzip
import json
import time
from urllib.parse import urlsplit, parse_qs
import socketserver
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with self.server.tls.wrap_socket(self.request, server_side=True) as connection:
                connection.settimeout(5)
                stream = connection.makefile("rb")
                line = stream.readline(32768).decode().strip()
                headers = {}
                while True:
                    header = stream.readline(32768)
                    if header == b"\r\n":
                        break
                    name, value = header.decode().split(":", 1)
                    headers[name.lower()] = value.strip()
                target = urlsplit(line.split(" ")[1])
                if target.path == "/multi-device/ping":
                    assert "authorization" not in headers
                    mode = parse_qs(target.query).get("mode", ["good"])[0]
                    if mode.startswith("slow"):
                        # No response: a successful competing route or caller
                        # cancellation must close this connection promptly.
                        if connection.recv(1) == b"":
                            with self.server.probe_lock:
                                self.server.cancelled_probes += 1
                        return
                    if mode == "good":
                        time.sleep(0.15)  # Let every concurrent probe establish TLS.
                    status = b"503 Unavailable" if mode == "status" else b"200 OK"
                    payload = b"not json" if mode == "malformed" else json.dumps({"deviceId": "other-device" if mode == "wrong" else "fixture-device"}).encode()
                    connection.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
                    return
                if target.path == "/probe-stats":
                    with self.server.probe_lock:
                        payload = json.dumps({"cancelled": self.server.cancelled_probes}).encode()
                    connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
                    return
                assert headers.get("authorization") == "Bearer fixture-session"
                assert "cookie" not in headers
                if headers.get("upgrade", "").lower() == "websocket":
                    accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
                    connection.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n\x81\x02ok")
                    frame = stream.read(2)
                    assert frame[0] == 0x81 and frame[1] & 0x80 and frame[1] & 0x7F < 126
                    mask = stream.read(4)
                    payload = stream.read(frame[1] & 0x7F)
                    payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
                    connection.sendall(bytes([0x81, len(payload)]) + payload)
                    stream.read(2)
                    return
                length = int(headers.get("content-length", "0"))
                body = stream.read(length)
                assert len(body) == length
                if "/api/redirect " in line:
                    connection.sendall(b"HTTP/1.1 302 Found\r\nLocation: https://example.invalid/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    return
                if "/api/declared-large " in line:
                    connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\nContent-Type: application/octet-stream\r\nConnection: close\r\n\r\n")
                    connection.recv(1)  # Client must reject headers without needing a body.
                    return
                if "/api/chunked-large " in line:
                    connection.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n200\r\n" + b"x" * 512 + b"\r\n0\r\n\r\n")
                    return
                if "/api/compressed-large " in line:
                    payload = gzip.compress(b"x" * 512)
                    connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
                    return
                if "range" in headers:
                    connection.sendall(b"HTTP/1.1 206 Partial Content\r\nContent-Range: bytes 0-2/10\r\nContent-Length: 3\r\nConnection: close\r\n\r\nfix")
                    return
                response = str(length).encode() if length else b"fixture-ok"
                connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(response)).encode() + b"\r\nConnection: close\r\n\r\n" + response)
        except (ssl.SSLError, ConnectionError, TimeoutError, socket.timeout):
            pass  # Expected when the client rejects our certificate pin.


def main():
    with tempfile.TemporaryDirectory(prefix="stimma-transport-") as directory:
        certificate, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(certificate), "-days", "1", "-subj", "/CN=localhost"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).hexdigest()
        with Server(("127.0.0.1", 0), Handler) as server:
            server.cancelled_probes = 0
            server.probe_lock = threading.Lock()
            server.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server.tls.load_cert_chain(certificate, key)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                subprocess.run([sys.argv[1], str(server.server_address[1]), fingerprint], check=True, timeout=60)
            finally:
                server.shutdown()


if __name__ == "__main__":
    main()
