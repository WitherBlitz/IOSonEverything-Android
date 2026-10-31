import socket
import unittest
from iosvm.vendor.tcpusb import listen


class TransportTests(unittest.TestCase):
    def test_tcp_listener_accepts_loopback_client_without_unix_socket_support(self):
        with listen("tcp:127.0.0.1:0") as server:
            with socket.create_connection(server.getsockname()) as client:
                with server.accept()[0] as accepted:
                    client.sendall(b"USB")
                    self.assertEqual(accepted.recv(3), b"USB")

    def test_tcp_listener_rejects_remote_bind_address(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            listen("tcp:0.0.0.0:18030")
