import unittest

from iosvm.vendor.muxd import Device, MuxConnection, TH_ACK, TH_SYN, TCP_HEADER
from iosvm.vendor.tcpusb import RET_SUCCESS, UsbError


class AcceptedLink:
    def __init__(self): self.writes = []
    def xfer(self, token, endpoint, data=b'', **kwargs):
        self.writes.append(bytes(data))
        return RET_SUCCESS, b''


def setup(sequence=0):
    link = AcceptedLink()
    device = Device(link)
    device.version = 2
    connection = MuxConnection(1, 12345, None)
    connection.established.set()
    connection.tx_seq = connection.tx_acked = sequence
    device.connections[1] = connection
    return device, connection, link


def acknowledge(device, connection, number, source=None):
    device._handle_tcp(TCP_HEADER.pack(source or connection.dport, connection.sport,
        connection.tx_ack, number, 5 << 4, TH_ACK, 1024, 0, 0))


class HistoryTests(unittest.TestCase):
    def test_syn_ack_on_second_connection_proves_earlier_global_prefix(self):
        device, first, link = setup()
        device._send_tcp(first, TH_ACK)
        device._send_tcp(first, TH_ACK, b'first connection')
        second = MuxConnection(2, 62078, None)
        device.connections[2] = second
        device._send_tcp(second, TH_SYN)
        device._handle_tcp(TCP_HEADER.pack(second.dport, second.sport, 0, 1,
            5 << 4, TH_SYN | TH_ACK, 1024, 0, 0))
        self.assertTrue(second.established.is_set())
        self.assertEqual(first.tx_acked, 0)
        self.assertFalse(first.transmitted)
        self.assertEqual(len(device.recent), 1)  # new ACK of SYN|ACK remains
        self.assertEqual(device.recent[0][0], 3)

    def test_lost_bare_ack_remains_recoverable_after_100_small_guest_frames(self):
        device, connection, link = setup()
        for _ in range(100): device._send_tcp(connection, TH_ACK)
        original = list(link.writes)
        connection.last_progress = -100
        device._resend_if_stuck()
        self.assertEqual(link.writes[100:], original)

    def test_only_valid_advanced_tcp_ack_retires_proven_mux_prefix(self):
        device, connection, link = setup()
        device._send_tcp(connection, TH_ACK)
        device._send_tcp(connection, TH_ACK, b'abcd')
        device._send_tcp(connection, TH_ACK)
        for invalid in [0, 5, 0xffffffff]: acknowledge(device, connection, invalid)
        self.assertEqual(connection.tx_acked, 0)
        self.assertEqual(len(device.recent), 3)
        acknowledge(device, connection, 2)
        acknowledge(device, connection, 1)  # stale ACK cannot move backwards
        self.assertEqual(connection.tx_acked, 2)
        self.assertEqual(len(device.recent), 3)
        acknowledge(device, connection, 4)
        self.assertEqual(len(device.recent), 1)  # later bare ACK still unproved

    def test_ack_proof_handles_tcp_wrap_and_rejects_wrong_remote_port(self):
        device, connection, link = setup(0xfffffffe)
        device._send_tcp(connection, TH_ACK, b'abcd')
        acknowledge(device, connection, 2, source=54321)
        self.assertEqual(len(device.recent), 1)
        acknowledge(device, connection, 2)
        self.assertEqual(connection.tx_acked, 2)
        self.assertEqual(len(device.recent), 0)

    def test_history_limit_fails_before_transmission_or_sequence_consumption(self):
        device, connection, link = setup()
        device.history_packet_limit = 2
        device._send_tcp(connection, TH_ACK)
        device._send_tcp(connection, TH_ACK)
        sequence = device.tx_seq
        with self.assertRaises(UsbError): device._send_tcp(connection, TH_ACK)
        self.assertEqual(device.tx_seq, sequence)
        self.assertEqual(len(link.writes), 2)


if __name__ == '__main__': unittest.main()
