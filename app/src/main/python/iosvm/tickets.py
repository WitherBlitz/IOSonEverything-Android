# SPDX-License-Identifier: GPL-3.0-or-later
"""Ticket preparation ported from MakrSas/Inferno-iOS Ticket.swift and IMG4.swift.

The public research template is downloaded separately; no Apple OS image is
included with this source. Unknown certificate nodes are retained verbatim.
"""
import plistlib
from .firmware import tlv


class Node:
    def __init__(self, identifier, value=b'', children=None):
        self.identifier, self.value, self.children = identifier, value, children

    def encode(self):
        body = b''.join(n.encode() for n in self.children) if self.children is not None else self.value
        encoded = tlv(0, body)
        return self.identifier + encoded[1:]

    def code(self):
        if self.identifier[0] & 0xc0 != 0xc0:
            return None
        number = 0
        for byte in self.identifier[1:]:
            number = (number << 7) | (byte & 0x7f)
        try:
            return number.to_bytes(4, 'big').decode('ascii')
        except (OverflowError, UnicodeDecodeError):
            return None


def parse(data, at=0, depth=0):
    if depth > 40 or at >= len(data):
        raise ValueError('Invalid ticket DER nesting')
    start = at
    byte = data[at]; at += 1
    if byte & 31 == 31:
        while True:
            if at >= len(data) or at - start > 9:
                raise ValueError('Invalid ticket DER tag')
            byte = data[at]; at += 1
            if not byte & 128:
                break
    identifier = data[start:at]
    if at >= len(data):
        raise ValueError('Missing ticket DER length')
    length = data[at]; at += 1
    if length & 128:
        count = length & 127
        if not 0 < count <= 4 or at + count > len(data):
            raise ValueError('Invalid ticket DER length')
        length = int.from_bytes(data[at:at + count], 'big'); at += count
    end = at + length
    if end > len(data):
        raise ValueError('Truncated ticket DER')
    if identifier[0] & 0x20:
        children = []
        while at < end:
            child, at = parse(data, at, depth + 1); children.append(child)
        if at != end:
            raise ValueError('Ticket child exceeds parent')
        return Node(identifier, children=children), end
    return Node(identifier, data[at:end]), end


AP_COMPONENTS = {'rosi': 'OS', 'krnl': 'KernelCache', 'dtre': 'DeviceTree',
                 'rdtr': 'RestoreDeviceTree', 'trst': 'StaticTrustCache', 'rtsc': 'RestoreTrustCache',
                 'mtfw': 'Multitouch', 'anef': 'ANE', 'aopf': 'AOP', 'avef': 'AVE',
                 'hpas': 'Ap,HapticAssets', 'acfw': 'AudioCodecFirmware', 'gfxf': 'GFX',
                 'ispf': 'ISP', 'lphp': 'LeapHaptics', 'pmpf': 'PMP', 'siof': 'SIO',
                 'sepi': 'SEP', 'rsep': 'RestoreSEP', 'rdsk': 'RestoreRamDisk',
                 'isys': 'SystemVolume', 'msys': 'SystemVolumeCanonicalMetadata'}


def field(component, name):
    for node in component.children[0].children[1].children:
        if node.code() == name:
            return node.children[0].children[1]
    return None


def replace(node, value, tag):
    node.identifier, node.value, node.children = bytes([tag]), value, None


def integer(number):
    raw = number.to_bytes((number.bit_length() + 7) // 8 or 1, 'big')
    return (b'\0' + raw) if raw[0] & 128 else raw


def rewrite(components, identity, sep, touch_identity=True):
    mapping = AP_COMPONENTS if not sep else {k: AP_COMPONENTS[k] for k in
               ('rosi', 'krnl', 'dtre', 'rdtr', 'trst', 'rtsc', 'sepi', 'rsep')}
    for component in components:
        code = component.code()
        if code in mapping:
            entry = identity['Manifest'].get(mapping[code])
            digest = field(component, 'DGST')
            if entry and digest is not None:
                replace(digest, entry['Digest'], 4)
        elif code in ('rfta', 'ftap', 'rfts', 'ftsp'):
            name = component.children[0].children[0]
            name.value = name.value[::-1]
        elif code == 'MANP' and sep:
            chip = field(component, 'CHIP')
            if chip is not None:
                replace(chip, integer(0x8030), 2)
            if touch_identity:
                ecid, nonce = field(component, 'ECID'), field(component, 'snon')
                if ecid is not None:
                    replace(ecid, integer(0x1122334455667788), 2)
                if nonce is not None:
                    replace(nonce, bytes.fromhex('feedface') * 5, 4)


def forge(template, identity, sep=False):
    raw = plistlib.loads(template)['ApImg4Ticket']
    root, end = parse(raw)
    if end != len(raw) or root.children[0].value != b'IM4M':
        raise ValueError('Template is not an IM4M ticket')
    components = root.children[2].children[0].children[0].children[1].children
    rewrite(components, identity, sep)
    if sep:
        tbs = root.children[4].children[0].children[0]
        extensions = next(n for n in tbs.children if n.identifier == b'\xa3').children[0].children
        value = extensions[4].children[-1]
        inner, end = parse(value.value)
        if end != len(value.value):
            raise ValueError('Invalid certificate manifest')
        rewrite(inner.children, identity, True, False)
        value.value = inner.encode()
    return root.encode()
