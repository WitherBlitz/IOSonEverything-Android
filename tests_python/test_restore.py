import io
import plistlib
import struct
import unittest
from iosvm.restore import PlistChannel, AsrChannel, read_image_range, connect_asr


class FragmentedSocket:
    def __init__(self, data):
        self.data = bytearray(data)
        self.sent = bytearray()
    def recv(self, size):
        data = bytes(self.data[:min(size, 3)])
        del self.data[:len(data)]
        return data
    def sendall(self, data):
        self.sent += data


class RestoreTests(unittest.TestCase):
    def test_asr_cancel_after_refused_connection_stops_before_retry(self):
        stopped = False
        def connect(port):
            nonlocal stopped
            if stopped:
                raise AssertionError('Cancelled restore tried another guest connection')
            stopped = True
            raise ConnectionError('not ready')
        with self.assertRaises(InterruptedError):
            connect_asr(connect, 12345, lambda: stopped)

    def test_restored_reads_fragmented_big_endian_frame(self):
        payload = plistlib.dumps({"Status": 14})
        channel = PlistChannel(FragmentedSocket(struct.pack(">I", len(payload)) + payload))
        self.assertEqual(channel.receive(), {"Status": 14})

    def test_restored_rejects_oversized_frame_before_allocating(self):
        with self.assertRaisesRegex(ValueError, "length"):
            PlistChannel(FragmentedSocket(b"\x7f\xff\xff\xff")).receive()

    def test_restored_reports_truncated_connection(self):
        with self.assertRaises(ConnectionError):
            PlistChannel(FragmentedSocket(b"\x00\x00")).receive()

    def test_asr_retains_second_xml_message_after_coalesced_receive(self):
        channel = AsrChannel(FragmentedSocket(plistlib.dumps({"Command": "Initiate"}) +
                                             plistlib.dumps({"Command": "Payload"})))
        self.assertEqual(channel.receive()["Command"], "Initiate")
        self.assertEqual(channel.receive()["Command"], "Payload")

    def test_asr_offset_cannot_escape_the_system_image(self):
        image = io.BytesIO(b"PRIVATE" + b"SYSTEM" + b"PRIVATE")
        self.assertEqual(read_image_range(image, (7, 6), 1, 3), b"YST")
        for offset, size in [(-1, 1), (5, 2), (0, -1)]:
            with self.subTest(offset=offset, size=size), self.assertRaises(ValueError):
                read_image_range(image, (7, 6), offset, size)
