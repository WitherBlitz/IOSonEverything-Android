# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict preparation primitives for the one selected iPhone 11 guest profile.

Container and restore conventions follow MakrSas/Inferno-iOS (GPLv3),
app/Sources/IMG4.swift, SEPFirmware.swift and IPSW.swift.
"""
import struct
import zipfile


def select_identity(manifest):
    if manifest.get("ProductBuildVersion") != "18A5351d":
        raise ValueError("Unsupported iOS build; expected 18A5351d")
    if "iPhone12,1" not in manifest.get("SupportedProductTypes", []):
        raise ValueError("Unsupported device; expected iPhone12,1")
    matches = []
    for identity in manifest.get("BuildIdentities", []):
        info = identity.get("Info", {})
        if (info.get("DeviceClass") == "n104ap" and info.get("RestoreBehavior") == "Erase"
                and "Research" not in info.get("Variant", "")):
            matches.append(identity)
    if len(matches) != 1:
        raise ValueError("Expected exactly one production erase identity")
    return matches[0]


def stored_range(archive, name):
    """Return the absolute raw-file range ASR may read without buffering a DMG."""
    info = archive.getinfo(name)
    if info.compress_type != zipfile.ZIP_STORED or info.flag_bits & 1:
        raise ValueError("ASR requires a stored, unencrypted system image")
    source = archive.fp
    previous = source.tell()
    try:
        source.seek(info.header_offset)
        header = source.read(30)
        if len(header) != 30 or header[:4] != b"PK\x03\x04":
            raise ValueError("Invalid ZIP local header")
        filename, extra = struct.unpack_from("<HH", header, 26)
        offset = info.header_offset + 30 + filename + extra
        source.seek(0, 2)
        if offset + info.file_size > source.tell():
            raise ValueError("Truncated system image")
        return offset, info.file_size
    finally:
        source.seek(previous)


def tlv(tag, body):
    n = len(body)
    if n < 128:
        size = bytes([n])
    else:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        size = bytes([128 + len(raw)]) + raw
    return bytes([tag]) + size + body


def read_element(data, at=0):
    if at + 2 > len(data):
        raise ValueError("Truncated DER header")
    tag, length = data[at:at + 2]
    at += 2
    if tag & 31 == 31:
        raise ValueError("Unexpected DER tag")
    if length & 128:
        count = length & 127
        if not 0 < count <= 4 or at + count > len(data):
            raise ValueError("Invalid DER length")
        length = int.from_bytes(data[at:at + count], "big")
        at += count
    end = at + length
    if end > len(data):
        raise ValueError("Truncated DER payload")
    return tag, at, end


def container_fields(data, magic):
    tag, start, end = read_element(data)
    if tag != 0x30 or end != len(data):
        raise ValueError("Invalid IMG4 container")
    fields = []
    at = start
    while at < end:
        tag, body, following = read_element(data, at)
        fields.append((tag, data[body:following]))
        at = following
    if not fields or fields[0] != (0x16, magic):
        raise ValueError("Unexpected IMG4 magic")
    return fields


def personalize(im4p, ticket):
    fields = container_fields(im4p, b"IM4P")
    if len(fields) < 4 or [x[0] for x in fields[:4]] != [0x16, 0x16, 0x16, 4]:
        raise ValueError("Invalid IM4P fields")
    # Ticket private tags are retained verbatim, not decoded or rewritten here.
    tag, start, end = read_element(ticket)
    first_tag, body, _ = read_element(ticket, start)
    if tag != 0x30 or end != len(ticket) or first_tag != 0x16 or ticket[body:body + 4] != b"IM4M":
        raise ValueError("Invalid IM4M ticket")
    return tlv(0x30, tlv(0x16, b"IMG4") + im4p + tlv(0xa0, ticket))


def decrypt_sep(payload, iv, key):
    if len(iv) != 16 or len(key) != 32 or not payload or len(payload) % 16:
        raise ValueError("SEP requires AES-256-CBC and complete blocks")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        # Android's platform cipher avoids a second native crypto dependency.
        from java import jclass
        cipher = jclass("javax.crypto.Cipher").getInstance("AES/CBC/NoPadding")
        cipher.init(2, jclass("javax.crypto.spec.SecretKeySpec")(key, "AES"),
                    jclass("javax.crypto.spec.IvParameterSpec")(iv))
        return bytes(cipher.doFinal(payload))
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(payload) + decryptor.finalize()


def rebuild_sep(encrypted, ticket, iv, key):
    fields = container_fields(encrypted, b"IM4P")
    if len(fields) < 4 or fields[3][0] != 4:
        raise ValueError("Invalid encrypted SEP payload")
    plain = decrypt_sep(fields[3][1], iv, key)
    rebuilt = tlv(0x30, tlv(0x16, b"IM4P") + tlv(0x16, b"rsep") +
                  tlv(0x16, b"none") + tlv(4, plain))
    return personalize(rebuilt, ticket)
