import struct
import unittest

from iosvm.vendor.muxd import Device, MUX_PROTO_TCP, MuxConnection
from iosvm.vendor.tcpusb import USB_TOKEN_IN, USB_TOKEN_OUT, RET_NAK, RET_SUCCESS, RET_STALL, UsbError


class DuplexLink:
    def __init__(self):
        self.drained = False
        self.writes = []
        self.reply = struct.pack('!II', MUX_PROTO_TCP, 12) + b'ACK!'

    def xfer(self, token, endpoint, data=b'', **kwargs):
        if token == USB_TOKEN_IN:
            self.drained = True
            return RET_SUCCESS, self.reply
        self.writes.append(bytes(data))
        return (RET_SUCCESS if self.drained else RET_NAK), b''


class BackpressureTests(unittest.TestCase):
    def test_stream_packets_end_before_usb_packet_boundary(self):
        class Accepted:
            def __init__(self): self.writes = []
            def xfer(self, token, endpoint, data=b'', **kwargs):
                self.writes.append(bytes(data)); return RET_SUCCESS, b''
        link = Accepted()
        device = Device(link)
        device.version = 2
        connection = MuxConnection(1, 12345, None)
        connection.rx_win = 1 << 20
        source = bytes(range(256)) * 256
        connection.outgoing += source
        device._flush(connection)
        self.assertTrue(all(packet and len(packet) % 512 for packet in link.writes))
        self.assertEqual(b''.join(packet[36:] for packet in link.writes), source)

    def test_resend_keeps_original_mux_numbers_without_consuming_new_numbers(self):
        class Accepted:
            def __init__(self): self.writes = []
            def xfer(self, token, endpoint, data=b'', **kwargs):
                self.writes.append(bytes(data)); return RET_SUCCESS, b''
        link = Accepted()
        device = Device(link)
        device.version = 2
        device._send_packet(MUX_PROTO_TCP, payload=b'first')
        connection = MuxConnection(1, 12345, None)
        connection.tx_seq = 5
        device.connections[1] = connection
        connection.last_progress = -100
        device._resend_if_stuck()
        self.assertEqual(link.writes, [link.writes[0], link.writes[0]])
        self.assertEqual(device.tx_seq, 1)

    def test_pending_in_packet_is_drained_while_out_is_nak_then_out_retries_unchanged(self):
        link = DuplexLink()
        device = Device(link)
        device.ep_in, device.ep_out = 1, 2
        device._send_packet(MUX_PROTO_TCP, payload=b'restore bytes')
        self.assertEqual(link.writes[0], link.writes[1])
        self.assertEqual(device._take_packet(), (MUX_PROTO_TCP, b'ACK!'))

    def test_stall_is_failure_not_a_backpressure_retry(self):
        class Stalled:
            def xfer(self, *args, **kwargs): return RET_STALL, b''
        with self.assertRaises(UsbError):
            Device(Stalled())._send_packet(MUX_PROTO_TCP, payload=b'data')


if __name__ == '__main__':
    unittest.main()
