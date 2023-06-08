from collections import namedtuple

from mod_async import Return, async_task
from mod_websocket_server.util import skip_first

Request = namedtuple(
    "Request", ("method", "url", "protocol", "protocol_version", "headers")
)


@async_task
def read_request(stream):
    parser = request_parser()
    for _ in range(8):
        data = yield stream.receive(512)
        request = parser.send(data)
        if request:
            raise Return(request)
    else:
        raise AssertionError("Request too large")


@skip_first
def header_line_splitter():
    read_buffer = bytes()
    while True:
        parts = read_buffer.split("\r\n")
        read_buffer = parts[-1]
        read_buffer += yield parts[:-1]


@skip_first
def request_parser():
    splitter = header_line_splitter()
    lines = []
    headers = dict()

    while len(lines) < 1:
        data = yield
        lines.extend(splitter.send(data))

    method, url, protocol_str = lines[0].split(" ")
    protocol, protocol_version = protocol_str.split("/")

    while "" not in lines:
        data = yield
        lines.extend(splitter.send(data))

    for line in lines[1:-1]:
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    yield Request(
        method=method.upper(),
        url=url.lower(),
        protocol=protocol.upper(),
        protocol_version=protocol_version.lower(),
        headers=headers,
    )
