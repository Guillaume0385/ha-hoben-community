"""Verified TLS over MemoryBIO, never a TCP connection or real identity.

Reuse existing, unchanged V4 vectors. No fixture from the publication-refused
HA test file is copied, moved, concealed or imported here.
"""

import asyncio
import ssl
import subprocess
from types import SimpleNamespace

from tests.test_association import DEVICE_GUID, USER_GUID
from tests.test_v4_session import opened_prefix


def certificate_files(folder):
    key, cert = folder / "local.key", folder / "local.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=myhoben.fr",
            "-addext",
            "subjectAltName=DNS:myhoben.fr",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=10,
    )
    key.chmod(0o600)
    return key, cert


class MemoryTlsPeer(asyncio.Transport):
    def __init__(self, client_context, server_context, *, close_ack=True):
        self.cin, self.cout, self.sin, self.sout = [ssl.MemoryBIO() for _ in range(4)]
        self.client = client_context.wrap_bio(
            self.cin, self.cout, server_side=False, server_hostname="myhoben.fr"
        )
        self.server = server_context.wrap_bio(self.sin, self.sout, server_side=True)
        complete = set()
        for _ in range(64):
            for name, tls in (("client", self.client), ("server", self.server)):
                try:
                    tls.do_handshake()
                    complete.add(name)
                except ssl.SSLWantReadError:
                    pass
                self.transfer()
            if len(complete) == 2:
                break
        assert len(complete) == 2
        self.reader = asyncio.StreamReader()
        self.protocol = asyncio.StreamReaderProtocol(self.reader)
        self.protocol.connection_made(self)
        self.writer = asyncio.StreamWriter(
            self, self.protocol, self.reader, asyncio.get_running_loop()
        )
        self.close_ack = close_ack
        self.closed = False
        self.transmissions = []
        self.read_requests = 0
        self.on_read_request = None

    def transfer(self):
        for outgoing, incoming in ((self.cout, self.sin), (self.sout, self.cin)):
            data = outgoing.read()
            if data:
                incoming.write(data)

    def get_extra_info(self, name, default=None):
        return {"ssl_object": self.client, "sslcontext": self.client.context}.get(
            name, default
        )

    def is_closing(self):
        return self.closed

    def get_write_buffer_size(self):
        return 0

    def write(self, data):
        assert not self.closed
        self.client.write(data)
        self.transfer()
        request = self.server.read()
        self.transmissions.append(request)
        if request[:1] == b"\x03":
            self.deliver(opened_prefix())
        elif request[:1] == b"\x0d":
            self.read_requests += 1
            if self.on_read_request:
                self.on_read_request()
        else:
            assert request == b"\x0b"

    def deliver(self, data):
        self.server.write(data)
        self.transfer()
        self.reader.feed_data(self.client.read())

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.close_ack:
            # Real TLS close_notify round trip entirely inside the two BIOs.
            for _ in range(4):
                for tls in (self.client, self.server):
                    try:
                        tls.unwrap()
                    except ssl.SSLWantReadError:
                        pass
                    self.transfer()
            self.protocol.connection_lost(None)

    def abort(self):
        self.closed = True
        if self.close_ack:
            self.protocol.connection_lost(None)


def install_tls(monkeypatch, files, *, close_ack=True):
    key, cert = files
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=cert)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert, key)
    state = SimpleNamespace(peer=None, connections=0)

    async def direct(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def connect(host, port, **kwargs):
        assert (host, port) == ("myhoben.fr", 465)
        assert kwargs["server_hostname"] == host
        assert kwargs["ssl"].verify_mode == ssl.CERT_REQUIRED
        assert kwargs["ssl"].check_hostname is True
        state.connections += 1
        assert state.connections == 1
        state.peer = MemoryTlsPeer(context, server, close_ack=close_ack)
        return state.peer.reader, state.peer.writer

    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    monkeypatch.setattr(asyncio, "to_thread", direct)
    return state, USER_GUID, DEVICE_GUID
