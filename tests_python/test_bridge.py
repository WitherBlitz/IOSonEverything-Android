import pathlib
import socket
import tempfile
import threading
import unittest
from iosvm.vendor.muxd import Muxd


class BridgeLifecycleTests(unittest.TestCase):
    def test_stop_releases_listeners_so_retry_does_not_keep_background_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Muxd('tcp:127.0.0.1:0', 'tcp:127.0.0.1:0', str(pathlib.Path(directory) / 'pairs'))
            threads = [threading.Thread(target=method, daemon=True) for method in
                       (bridge.serve_usb, bridge.serve_clients)]
            try:
                for thread in threads:
                    thread.start()
                self.assertTrue(bridge.usb_ready.wait(2))
                self.assertTrue(bridge.clients_ready.wait(2))
            finally:
                bridge.stop()
                for thread in threads:
                    thread.join(2)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertTrue(all(server.fileno() == -1 for server in bridge.servers))
