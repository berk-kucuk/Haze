"""
Wire framing: 4-byte big-endian length prefix + JSON payload.
Max message size: 1 MB.
File chunks are 256 KB raw → ~341 KB base64 → ~470 KB after session-encryption,
which fits comfortably within the 1 MB envelope limit.
"""

import json
import struct
import asyncio
import uuid as _uuid

_MAX_SIZE = 1 * 1024 * 1024  # 1 MB
_PREFIX = 4

CHUNK_SIZE = 256 * 1024  # 256 KB raw per file chunk


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

def make_chat(nick: str, content: str, msg_id: str | None = None) -> dict:
    return {"type": "chat", "nick": nick, "content": content,
            "msg_id": msg_id or str(_uuid.uuid4())}

def make_join(nick: str) -> dict:
    return {"type": "join", "nick": nick}

def make_leave(nick: str) -> dict:
    return {"type": "leave", "nick": nick}

def make_panic(nick: str) -> dict:
    return {"type": "panic", "nick": nick}

def make_userlist(users: list[str]) -> dict:
    return {"type": "userlist", "users": users}

def make_kicked() -> dict:
    return {"type": "kicked"}

def make_file_start(nick: str, file_id: str, filename: str, mime: str,
                    total_size: int, total_chunks: int) -> dict:
    return {
        "type": "file_start",
        "nick": nick,
        "file_id": file_id,
        "filename": filename,
        "mime": mime,
        "total_size": total_size,
        "total_chunks": total_chunks,
    }

def make_file_chunk(nick: str, file_id: str, chunk_index: int, data_b64: str) -> dict:
    return {
        "type": "file_chunk",
        "nick": nick,
        "file_id": file_id,
        "chunk_index": chunk_index,
        "data": data_b64,
    }

def make_file_end(nick: str, file_id: str) -> dict:
    return {"type": "file_end", "nick": nick, "file_id": file_id}

def make_typing(nick: str, is_typing: bool) -> dict:
    return {"type": "typing", "nick": nick, "state": is_typing}

def make_delete(nick: str, msg_id: str) -> dict:
    return {"type": "delete", "nick": nick, "msg_id": msg_id}

def make_edit(nick: str, msg_id: str, content: str) -> dict:
    return {"type": "edit", "nick": nick, "msg_id": msg_id, "content": content}

def make_ping(ts: float) -> dict:
    return {"type": "ping", "ts": ts}

def make_pong(ts: float) -> dict:
    return {"type": "pong", "ts": ts}
