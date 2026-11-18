import gc


def secure_wipe_bytearray(buf: bytearray) -> None:
    for i in range(len(buf)):
        buf[i] = 0


# There is deliberately no wipe_string(). The one that was here computed the
# buffer address as id(s) + getsizeof("") - len(s) - 1, which points into the
# object header rather than at the characters: it overwrote the string's
# hash/length/kind fields and killed the interpreter (SystemError, then
# "free(): invalid pointer" or a segfault) even for a 10-character string
# (audit H7). Python strings are immutable and may be interned or
# shared, so there is no safe in-place wipe; keep secrets in bytearray and use
# secure_wipe_bytearray().


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
