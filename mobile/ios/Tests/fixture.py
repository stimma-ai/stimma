"""Disposable loopback TLS fixture; never contacts an account or real backend.

Speaks HTTP/1.1 with keep-alive like the remote listener: each connection
serves requests until the client closes it or it idles out, every response
names its connection (X-Fixture-Connection) and advertises the idle timeout.
/fixture-stats reports what reached the server, so checks can prove reuse,
cancellation and that a mutation was not replayed.
"""
import base64
import collections
import gzip
import hashlib
import itertools
import json
import socket
import socketserver
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

KEEP_ALIVE_SECONDS = 30


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        with server.lock:
            self.connection_id = next(server.connection_ids)
        try:
            with server.tls.wrap_socket(self.request, server_side=True) as connection:
                self.connection = connection
                connection.settimeout(KEEP_ALIVE_SECONDS + 5)
                self.stream = connection.makefile("rb")
                while self.serve_one():
                    pass
        except (ssl.SSLError, ConnectionError, TimeoutError, socket.timeout, OSError):
            pass  # Expected when the client rejects our certificate pin or hangs up.

    def count(self, key):
        with self.server.lock:
            self.server.counts[key] += 1

    def send(self, status, body=b"", headers=(), keep=True):
        lines = [b"HTTP/1.1 " + status.encode()]
        lines.append(b"X-Fixture-Connection: " + str(self.connection_id).encode())
        for name, value in headers:
            lines.append(name.encode() + b": " + value.encode())
        if not any(name.lower() in ("content-length", "transfer-encoding") for name, _ in headers):
            lines.append(b"Content-Length: " + str(len(body)).encode())
        if keep:
            lines.append(b"Keep-Alive: timeout=" + str(KEEP_ALIVE_SECONDS).encode())
        else:
            lines.append(b"Connection: close")
        self.connection.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + body)
        return keep

    def reset(self):
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        self.connection.close()
        return False

    def wait_for_client_close(self, key):
        try:
            if self.connection.recv(1) == b"":
                self.count(key)
        except (ssl.SSLError, ConnectionError, OSError):
            self.count(key)
        return False

    def serve_one(self):
        line = self.stream.readline(32768).decode()
        if not line:
            return False
        method, raw_target, _ = line.strip().split(" ")
        headers = {}
        while True:
            header = self.stream.readline(32768)
            if header in (b"\r\n", b""):
                break
            name, value = header.decode().split(":", 1)
            headers[name.lower()] = value.strip()
        target = urlsplit(raw_target)
        path = target.path
        query = parse_qs(target.query)
        if path == "/fixture-stats":
            with self.server.lock:
                payload = json.dumps({f"{m} {p}": n for (m, p), n in self.server.counts.items()}).encode()
            return self.send("200 OK", payload, keep=False)
        self.count((method, path))
        if path == "/multi-device/ping":
            assert "authorization" not in headers
            mode = query.get("mode", ["good"])[0]
            if mode.startswith("slow"):
                # No response: a successful competing route or caller
                # cancellation must close this connection promptly.
                return self.wait_for_client_close(("cancelled", "probe"))
            if mode == "good":
                time.sleep(0.15)  # Let every concurrent probe establish TLS.
            status = "503 Unavailable" if mode == "status" else "200 OK"
            payload = b"not json" if mode == "malformed" else json.dumps({"deviceId": "other-device" if mode == "wrong" else "fixture-device"}).encode()
            return self.send(status, payload)
        if path == "/probe-stats":
            with self.server.lock:
                payload = json.dumps({"cancelled": self.server.counts[("cancelled", "probe")]}).encode()
            return self.send("200 OK", payload, keep=False)
        assert headers.get("authorization") == "Bearer fixture-session", headers.get("authorization")
        for private in ("cookie", "origin", "referer", "x-forwarded-for", "x-private", "sec-fetch-site", "proxy-authorization"):
            assert private not in headers, private
        if headers.get("upgrade", "").lower() == "websocket":
            accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            self.connection.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n\x81\x02ok")
            frame = self.stream.read(2)
            assert frame[0] == 0x81 and frame[1] & 0x80 and frame[1] & 0x7F < 126
            mask = self.stream.read(4)
            payload = self.stream.read(frame[1] & 0x7F)
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            self.connection.sendall(bytes([0x81, len(payload)]) + payload)
            self.stream.read(2)
            return False
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            assert "content-length" in headers, "mutations must state their length"
        length = int(headers.get("content-length", "0"))
        if path == "/api/drop" or (path == "/api/drop-once" and self.first(query["key"][0])):
            self.stream.read(length)
            return self.reset()  # The request arrived; its outcome is unknown to the client.
        body = self.stream.read(length)
        assert len(body) == length
        if path == "/api/redirect":
            return self.send("302 Found", headers=[("Location", "https://example.invalid/")])
        if path == "/api/bad-head":
            self.connection.sendall(b"HTTP/1.1 2x0 Nope\r\n\r\n")
            return False
        if path == "/api/declared-large":
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\nContent-Type: application/octet-stream\r\nConnection: close\r\n\r\n")
            self.connection.settimeout(5)  # As before keep-alive: give up after 5 s if the client waits for body bytes.
            self.connection.recv(1)
            return False
        if path == "/api/chunked-large":
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n200\r\n" + b"x" * 512 + b"\r\n0\r\n\r\n")
            return False
        if path == "/api/compressed-large":
            return self.send("200 OK", gzip.compress(b"x" * 512), [("Content-Encoding", "gzip")], keep=False)
        if path == "/api/gzip":
            offered = "gzip" in headers.get("accept-encoding", "")
            payload = b'{"items":"' + b"repetitive " * 400 + b'"}'
            if offered:
                return self.send("200 OK", gzip.compress(payload), [("Content-Type", "application/json"), ("Content-Encoding", "gzip"), ("Vary", "Accept-Encoding"), ("ETag", 'W/"g1"')])
            return self.send("200 OK", payload, [("Content-Type", "application/json"), ("Vary", "Accept-Encoding")])
        if path == "/api/echo-headers":
            return self.send("200 OK", json.dumps(headers).encode(), [("Content-Type", "application/json"), ("Set-Cookie", "server=secret"), ("Connection", "x-hop"), ("X-Hop", "1")])
        if path == "/api/close-after":
            self.send("200 OK", b"closing-soon")
            time.sleep(0.3)
            return False  # The server ends an idle keep-alive connection on its own.
        if path == "/api/etag":
            if headers.get("if-none-match") == '"v1"':
                return self.send("304 Not Modified", headers=[("ETag", '"v1"')])
            return self.send("200 OK", b"tagged", [("ETag", '"v1"')])
        if path == "/api/chunked":
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nX-Fixture-Connection: " + str(self.connection_id).encode() + b"\r\n\r\n")
            for _ in range(50):
                self.connection.sendall(b"800\r\n" + b"c" * 2048 + b"\r\n")
            self.connection.sendall(b"0\r\n\r\n")
            return True
        if path == "/api/stream":
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nfirst\r\n")
            time.sleep(1.5)
            self.connection.sendall(b"4\r\nlast\r\n0\r\n\r\n")
            return True
        if path == "/api/until-close":
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nno-length-body")
            return False
        if path == "/api/large":
            size = 4 * 1024 * 1024
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: " + str(size).encode() + b"\r\n\r\n")
            chunk = b"L" * 65536
            for _ in range(size // len(chunk)):
                self.connection.sendall(chunk)
            return True
        if path == "/api/hang":
            return self.wait_for_client_close(("closed", "/api/hang"))
        if path == "/api/slow-body":
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n" + b"s" * 10)
            return self.wait_for_client_close(("closed", "/api/slow-body"))
        if "range" in headers:
            return self.send("206 Partial Content", b"fix", [("Content-Range", "bytes 0-2/10")])
        if method == "HEAD":
            self.connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nKeep-Alive: timeout=30\r\nX-Fixture-Connection: " + str(self.connection_id).encode() + b"\r\n\r\n")
            return True
        response = str(length).encode() if length else b"fixture-ok"
        return self.send("200 OK", response)

    def first(self, key):
        with self.server.lock:
            seen = key in self.server.seen
            self.server.seen.add(key)
        return not seen


def main():
    with tempfile.TemporaryDirectory(prefix="stimma-transport-") as directory:
        certificate, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(certificate), "-days", "1", "-subj", "/CN=localhost"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).hexdigest()
        with Server(("127.0.0.1", 0), Handler) as server:
            server.counts = collections.Counter()
            server.seen = set()
            server.connection_ids = itertools.count(1)
            server.lock = threading.Lock()
            server.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server.tls.load_cert_chain(certificate, key)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                subprocess.run([sys.argv[1], str(server.server_address[1]), fingerprint], check=True, timeout=180)
            finally:
                server.shutdown()


if __name__ == "__main__":
    main()
