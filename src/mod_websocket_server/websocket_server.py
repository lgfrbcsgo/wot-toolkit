import struct
from base64 import b64encode
from collections import deque
from hashlib import sha1
from typing import Pattern

from mod_async import Return, async_task, timeout
from mod_async_server import StreamClosed
from mod_logging import LOG_NOTE
from mod_websocket_server.frame import Frame, OpCode
from mod_websocket_server.http import read_request

HANDSHAKE_KEY = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class MessageStream(object):
    def __init__(self, stream, handshake_headers):
        self.handshake_headers = handshake_headers
        self._stream = stream
        self._frame_parser = Frame.multi_parser()
        self._incoming_message_queue = deque()

    @property
    def addr(self):
        return self._stream.addr

    @property
    def peer_addr(self):
        return self._stream.peer_addr

    @async_task
    def receive_message(self):
        while len(self._incoming_message_queue) == 0:
            data = yield self._stream.receive(512)
            frames = self._frame_parser.send(data)
            for frame in frames:
                yield self._handle_frame(frame)

        raise Return(self._incoming_message_queue.popleft())

    @async_task
    def send_message(self, payload):
        frame = Frame(True, OpCode.TEXT, None, encode_utf8(payload))
        yield self._send_frame(frame)

    @async_task
    def close(self, code=1000, reason=""):
        payload = struct.pack("!H", code) + encode_utf8(reason)
        close = Frame(True, OpCode.CLOSE, None, payload)
        try:
            yield self._send_frame(close)
        except StreamClosed:
            pass
        finally:
            self._stream.close()

    @async_task
    def _handle_frame(self, frame):
        if not frame.fin:
            raise AssertionError("Message fragmentation is not supported.")

        if frame.op_code == OpCode.TEXT:
            message = frame.payload.decode("utf8")
            self._incoming_message_queue.append(message)
        elif frame.op_code == OpCode.BINARY:
            raise AssertionError("Binary frames are not supported.")
        elif frame.op_code == OpCode.CONTINUATION:
            raise AssertionError("Message fragmentation is not supported.")
        elif frame.op_code == OpCode.PING:
            pong = Frame(True, OpCode.PONG, None, frame.payload)
            yield self._send_frame(pong)
        elif frame.op_code == OpCode.CLOSE:
            if frame.payload:
                (code,) = struct.unpack("!H", frame.payload[:2])
                reason = frame.payload[2:].decode("utf8")
                yield self.close(code, reason)
            else:
                yield self.close()

    @async_task
    def _send_frame(self, frame):
        yield self._stream.send(frame.serialize())


def websocket_protocol(allowed_origins=None):
    def decorator(protocol):
        @async_task
        def wrapper(server, stream):
            request = yield timeout(2, read_request(stream))

            origin = request.headers.get("origin")
            if allowed_origins and not origin_matches(origin, allowed_origins):
                raise AssertionError("Origin {origin} is not allowed.".format(origin=origin))

            if request.url == "/ready":
                yield stream.send(make_ready_response(request))
                return

            yield stream.send(make_handshake_response(request))

            host, port = stream.peer_addr
            LOG_NOTE(
                "Websocket: {origin} ([{host}]:{port}) connected.".format(
                    origin=origin, host=host, port=port
                )
            )

            message_stream = MessageStream(stream, request.headers)
            try:
                yield protocol(server, message_stream)
            finally:
                LOG_NOTE(
                    "Websocket: {origin} ([{host}]:{port}) disconnected.".format(
                        origin=origin, host=host, port=port
                    )
                )
                yield message_stream.close()

        return wrapper

    return decorator


def make_handshake_response(request):
    if request.headers.get("sec-websocket-version") != "13":
        raise AssertionError("Unsupported Websocket version")

    key = request.headers.get("sec-websocket-key")
    if key is None:
        raise AssertionError("The 'sec-websocket-key' header is missing")

    accept = b64encode(sha1(key + HANDSHAKE_KEY).digest())

    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: WebSocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Accept: {accept}\r\n\r\n"
    ).format(accept=accept)


def make_ready_response(request):
    origin = request.headers.get("origin")
    if origin is None:
        return (
            "HTTP/1.1 204 No Content\r\n"
            "Vary: Origin\r\n\r\n"
        )

    return (
        "HTTP/1.1 204 No Content\r\n"
        "Access-Control-Allow-Origin: {origin}\r\n"
        "Vary: Origin\r\n\r\n"
    ).format(origin=origin)


def origin_matches(origin, allowed_origins):
    if origin is None:
        return True

    for allowed_origin in allowed_origins:
        if allowed_origin == origin:
            return True
        elif isinstance(allowed_origin, Pattern) and allowed_origin.match(origin):
            return True

    return False


def encode_utf8(data):
    if isinstance(data, str):
        data = data.decode("utf8")
    return data.encode("utf8")
