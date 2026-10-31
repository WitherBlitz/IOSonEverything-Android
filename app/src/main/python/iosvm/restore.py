# SPDX-License-Identifier: GPL-3.0-or-later
"""Host half of iOS 14 restored/ASR, ported from Inferno-iOS RestoreClient.swift.

Upstream: MakrSas/Inferno-iOS, revision 4bc39702871f5a118d96acbad4df7a675ddf14e0.
Only the selected iOS 14 profile is supported; unknown requests fail explicitly.
"""
import hashlib
import plistlib
import socket
import struct
import time
import uuid
import zipfile

from .firmware import personalize, stored_range


def receive_exact(sock, count):
    result = bytearray()
    while len(result) < count:
        data = sock.recv(count - len(result))
        if not data:
            raise ConnectionError("Guest connection closed")
        result += data
    return bytes(result)


class PlistChannel:
    def __init__(self, sock):
        self.sock = sock

    def send(self, message):
        raw = plistlib.dumps(message)
        self.sock.sendall(struct.pack(">I", len(raw)) + raw)

    def receive(self):
        size, = struct.unpack(">I", receive_exact(self.sock, 4))
        if not 0 < size < 64 * 1024 * 1024:
            raise ValueError("Invalid restored frame length")
        message = plistlib.loads(receive_exact(self.sock, size))
        if not isinstance(message, dict):
            raise ValueError("Expected restored dictionary")
        return message

    def request(self, message):
        self.send(message)
        return self.receive()


class AsrChannel:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = bytearray()
        self.checksums = False

    def receive(self):
        while True:
            end = self.buffer.find(b"</plist>")
            if end >= 0:
                end += 8
                raw = bytes(self.buffer[:end])
                del self.buffer[:end]
                return plistlib.loads(raw.strip())
            if len(self.buffer) > 1024 * 1024:
                raise ValueError("ASR XML message too large")
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("ASR closed")
            self.buffer += data

    def send_info(self, size):
        info = {"FEC Slice Stride": 40, "Packet Payload Size": 1450,
                "Packets Per FEC": 25, "Payload": {"Port": 1, "Size": size},
                "Stream ID": 1, "Version": 1}
        if self.checksums:
            info["Checksum Chunk Size"] = 131072
        self.sock.sendall(plistlib.dumps(info))


def read_image_range(source, image_range, offset, size):
    base, length = image_range
    if offset < 0 or size < 0 or offset + size > length or size > 8 * 1024 * 1024:
        raise ValueError("ASR range is outside the system image")
    source.seek(base + offset)
    data = source.read(size)
    if len(data) != size:
        raise ValueError("Truncated system image")
    return data


def mux_connect(port, address=("127.0.0.1", 27015)):
    if isinstance(address, str):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(20)
        sock.connect(address)
    else:
        sock = socket.create_connection(address, timeout=20)
    try:
        body = plistlib.dumps({"MessageType": "Connect", "DeviceID": 1,
                               "PortNumber": socket.htons(port), "ClientVersionString": "IOSonEverything"})
        sock.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, 1) + body)
        length, version, kind, tag = struct.unpack("<IIII", receive_exact(sock, 16))
        if not 16 <= length <= 1024 * 1024 or version != 1 or kind != 8 or tag != 1:
            raise ValueError("Invalid usbmuxd response")
        result = plistlib.loads(receive_exact(sock, length - 16))
        if result.get("Number") != 0:
            raise ConnectionError("Guest port %d is not ready (%s)" % (port, result))
        sock.settimeout(900)
        return sock
    except BaseException:
        sock.close()
        raise


def connect_asr(connect, port, cancelled):
    last = None
    for attempt in range(30):
        if cancelled():
            raise InterruptedError('Restore cancelled')
        try:
            return connect(port)
        except (OSError, ConnectionError) as error:
            last = error
        for tick in range(20):
            if cancelled():
                raise InterruptedError('Restore cancelled')
            time.sleep(0.1)
    raise ConnectionError('ASR never opened') from last


class RestoreClient:
    def __init__(self, ipsw_path, identity, ticket, connect=mux_connect, note=print, progress=None,
                 cancelled=lambda: False):
        self.path = ipsw_path
        self.archive = zipfile.ZipFile(ipsw_path)
        self.identity = identity
        self.manifest = identity["Manifest"]
        self.ticket = ticket
        self.connect = connect
        self.note = note
        self.progress = progress or (lambda stage, fraction: None)
        self.cancelled = cancelled

    def close(self):
        self.archive.close()

    def raw(self, component):
        return self.archive.read(self.manifest[component]["Info"]["Path"])

    def personalized(self, component):
        return personalize(self.raw(component), self.ticket)

    def nor_data(self, arguments):
        names = [name for name, entry in self.manifest.items()
                 if entry.get("Info", {}).get("Path") and
                 (entry["Info"].get("IsFirmwarePayload") or
                  (entry["Info"].get("IsSecondaryFirmwarePayload") and entry["Info"].get("IsLoadedByiBoot")))]
        names = sorted((n for n in names if n not in ("LLB", "RestoreSEP")),
                       key=lambda n: (not n.startswith("iBoot"), n))
        images = {n: self.personalized(n) for n in names}
        body = {"LlbImageData": self.personalized("LLB"),
                "NorImageData": images if "FlashVersion1" in arguments else list(images.values())}
        for component, key in [("RestoreSEP", "RestoreSEPImageData"), ("SEP", "SEPImageData"),
                               ("SepStage1", "SEPPatchImageData")]:
            if component in self.manifest:
                body[key] = self.personalized(component)
        return body

    def image_data(self, args, list_key, kind, data_key):
        kind = kind or args["ImageType"]
        names = sorted(n for n, e in self.manifest.items() if e.get("Info", {}).get(kind) is True)
        if args.get(list_key):
            return {list_key: names}
        name = args.get("ImageName")
        if name:
            body = {"ImageName": name}
            if name in names:
                body[data_key] = self.personalized(name)
            return body
        return {data_key: {n: self.personalized(n) for n in names}}

    def answer(self, request, restored):
        kind = request.get("DataType")
        args = request.get("Arguments", {})
        self.note("Guest requests " + str(kind))
        if kind == "SystemImageData":
            self.send_filesystem(request.get("DataPort", 12345))
            return
        if kind == "RootTicket":
            body = {"RootTicketData": self.ticket}
        elif kind in ("KernelCache", "DeviceTree"):
            body = {kind + "File": self.personalized(kind)}
        elif kind in ("SystemImageRootHash", "SystemImageCanonicalMetadata"):
            component = "SystemVolume" if kind == "SystemImageRootHash" else "Ap,SystemVolumeCanonicalMetadata"
            body = {kind + "File": self.personalized(component)}
        elif kind == "NORData":
            body = self.nor_data(args)
        elif kind == "BuildIdentityDict":
            body = {"BuildIdentityDict": self.identity, "Variant": args.get("Variant", "Erase")}
        elif kind == "ReceiptManifest":
            body = {"ReceiptManifest": self.manifest}
        elif kind in ("FDRTrustData", "FirmwareUpdaterPreflight", "DeviceRestoreInfoPreflight"):
            body = {}
        elif kind in ("PersonalizedData", "FUDData", "EANData"):
            spec = {"PersonalizedData": ("ImageList", None, "ImageData"),
                    "FUDData": ("FUDImageList", "IsFUDFirmware", "FUDImageData"),
                    "EANData": ("EANImageList", "IsEarlyAccessFirmware", "EANData")}
            body = self.image_data(args, *spec[kind])
        else:
            raise ValueError("Unsupported restore data request: " + str(kind))
        port = request.get("DataPort")
        if port:
            with self.connect(port) as channel:
                PlistChannel(channel).send(body)
        else:
            restored.send(body)

    def send_filesystem(self, port):
        image_range = stored_range(self.archive, self.manifest["OS"]["Info"]["Path"])
        sock = connect_asr(self.connect, port, self.cancelled)
        with sock, open(self.path, "rb") as source:
            asr = AsrChannel(sock)
            packet = asr.receive()
            if packet.get("Command") != "Initiate":
                raise ValueError("ASR did not initiate")
            asr.checksums = packet.get("Checksum Chunks", False)
            asr.send_info(image_range[1])
            while True:
                packet = asr.receive()
                kind = packet.get("Command")
                if kind == "Payload":
                    break
                if kind == "Initiate":
                    asr.checksums = packet.get("Checksum Chunks", asr.checksums)
                    asr.send_info(image_range[1])
                elif kind == "OOBData":
                    sock.sendall(read_image_range(source, image_range, packet["OOB Offset"], packet["OOB Length"]))
                else:
                    raise ValueError("Unsupported ASR command: " + str(kind))
            sent = 0
            while sent < image_range[1]:
                if self.cancelled():
                    raise InterruptedError('Restore cancelled')
                size = min(131072, image_range[1] - sent)
                chunk = read_image_range(source, image_range, sent, size)
                sock.sendall(chunk + (hashlib.sha1(chunk).digest() if asr.checksums else b""))
                sent += size
                self.progress("System image", sent / image_range[1])
            self.note("System image sent completely")

    def run(self):
        with self.connect(62078) as sock:
            restored = PlistChannel(sock)
            response = restored.request({"Request": "QueryType", "Label": "IOSonEverything"})
            self.note("Restore service: " + str(response))
            version = response.get("RestoreProtocolVersion")
            if not isinstance(version, int):
                raise ValueError("Guest did not return restore protocol version")
            options = {"AutoBootDelay": 0, "BootImageType": "User", "DFUFileType": "RELEASE",
                       "DataImage": False, "FirmwareDirectory": ".", "FlashNOR": True,
                       "KernelCacheType": "Release", "NORImageType": "production",
                       "RestoreBundlePath": "/tmp/IOSonEverything", "SystemImageType": "User",
                       "UpdateBaseband": True, "InstallDiags": False, "PersonalizedDuringPreflight": True,
                       "RootToInstall": False, "CreateFilesystemPartitions": True, "SystemImage": True,
                       "UUID": str(uuid.uuid4()), "SupportedDataTypes": SUPPORTED_DATA,
                       "SupportedMessageTypes": SUPPORTED_MESSAGES,
                       "SystemPartitionPadding": self.identity["Info"]["SystemPartitionPadding"]}
            restored.send({"Request": "StartRestore", "Label": "IOSonEverything",
                           "RestoreOptions": options, "RestoreProtocolVersion": version})
            while True:
                message = restored.receive()
                kind = message.get("MsgType")
                if kind in ("DataRequestMsg", "AsyncDataRequestMsg"):
                    self.answer(message, restored)
                elif kind == "StatusMsg":
                    self.note(str(message))
                    if message.get("Status") != 0:
                        raise RuntimeError("Guest restore failed: " + str(message))
                    restored.send({"MsgType": "ReceivedFinalStatusMsg"})
                    return
                elif kind == "ProgressMsg":
                    self.progress("Restore operation %s" % message.get("Operation"), message.get("Progress", 0) / 100)
                else:
                    self.note(str(message))


# Exact protocol capability maps are supplied by restore_caps.py, retained from
# the upstream Configurator-compatible implementation.
from .restore_caps import SUPPORTED_DATA, SUPPORTED_MESSAGES
