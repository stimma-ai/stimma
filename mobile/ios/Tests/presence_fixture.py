"""Exercise the native presence client using a disposable local WebSocket."""
import base64
import hashlib
import json
import socketserver
import subprocess
import sys
import threading
import time


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.connection.settimeout(10)
            assert self.rfile.readline().split()[1] == b'/account-events-v1'
            headers = {}
            while (line := self.rfile.readline()) != b'\r\n':
                key, value = line.decode().split(':', 1)
                headers[key.lower()] = value.strip()
            assert 'x-stimma-device-id' not in headers
            assert 'cookie' not in headers
            token = headers['authorization']
            assert token.startswith('Bearer fixture-')
            accept = base64.b64encode(hashlib.sha1((headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            self.connection.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
            frame = self.rfile.read(2)
            assert frame[0] == 0x81 and frame[1] & 0x80
            size = frame[1] & 127
            mask = self.rfile.read(4)
            payload = bytes(v ^ mask[i % 4] for i, v in enumerate(self.rfile.read(size)))
            assert json.loads(payload) == {'type': 'ping'}

            def send(data):
                value = json.dumps(data).encode()
                self.connection.sendall(bytes([0x81, len(value)]) + value)

            send({'type': 'pong'})
            if token == 'Bearer fixture-1':
                send({'type': 'account_event', 'reason': 'balance'})
                send({'type': 'account_event', 'reason': 'devices'})
                send({'type': 'account_event', 'reason': 'devices'})
                time.sleep(0.15)
                return  # Abrupt network loss; the client must reconnect itself.
            self.rfile.read(2)  # Wait for stop() to close the subscription.
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            self.server.errors.append(repr(error))


with socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler) as server:
    server.daemon_threads = True
    server.errors = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    result = subprocess.run([sys.argv[1], f'http://127.0.0.1:{server.server_address[1]}'], timeout=30)
    server.shutdown()
    assert not server.errors, server.errors
    sys.exit(result.returncode)
