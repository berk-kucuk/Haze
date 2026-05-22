"""
Wire framing: 4-byte big-endian length prefix + JSON payload.
Max message size: 1 MB.
"""

import json
import struct
import asyncio

_MAX_SIZE = 1 * 1024 * 1024  # 1 MB
_PREFIX = 4


async def send_msg(writer: asyncio.StreamWriter, data: dict) -> None:
    payload = json.dumps(data).encode()
    if len(payload) > _MAX_SIZE:
        raise ValueError("Message exceeds max size")
    writer.write(struct.pack(">I", len(payload)) + payload)
    await writer.drain()


async def recv_msg(reader: asyncio.StreamReader) -> dict:
    header = await reader.readexactly(_PREFIX)
    length = struct.unpack(">I", header)[0]
    if length > _MAX_SIZE:
        raise ValueError("Incoming message exceeds max size")
    payload = await reader.readexactly(length)
    return json.loads(payload.decode())


# ------------------------------------------------------------------
# Inner message constructors (plaintext payloads, will be encrypted)
# ------------------------------------------------------------------

def make_chat(nick: str, content: str) -> dict:
    return {"type": "chat", "nick": nick, "content": content}

def make_join(nick: str) -> dict:
    return {"type": "join", "nick": nick}

def make_leave(nick: str) -> dict:
    return {"type": "leave", "nick": nick}

def make_panic(nick: str) -> dict:
    return {"type": "panic", "nick": nick}

def make_userlist(users: list[str]) -> dict:
    return {"type": "userlist", "users": users}
