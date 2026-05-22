import gc
import os
import ctypes
import sys


def secure_wipe_bytearray(buf: bytearray) -> None:
    for i in range(len(buf)):
        buf[i] = 0


def wipe_string(s: str) -> None:
    """Best-effort overwrite of a Python str's internal buffer."""
    try:
        raw = (ctypes.c_char * len(s)).from_address(id(s) + sys.getsizeof("") - len(s) - 1)
        ctypes.memset(raw, 0, len(s))
    except Exception:
        pass


def full_wipe(message_list: list, crypto_objects: list) -> None:
    """
    Called on panic or normal quit.
    Clears message history and wipes crypto keys, then forces GC.
    """
    message_list.clear()

    for obj in crypto_objects:
        if hasattr(obj, "wipe"):
            obj.wipe()

    gc.collect()
