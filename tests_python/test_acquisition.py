import hashlib
import io
import pathlib
import tempfile
import unittest
import urllib.error
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from iosvm.acquisition import acquire, promote


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data); self.status = status; self.headers = headers or {}


class AcquisitionTests(unittest.TestCase):
    def test_short_http_body_is_retained_then_resumed_by_real_range_request(self):
        calls = []
        body = b'complete verified download'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                calls.append(self.headers.get('Range'))
                if len(calls) == 1:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body[:8])
                    self.close_connection = True
                else:
                    self.send_response(206)
                    self.send_header('Content-Length', str(len(body) - 8))
                    self.send_header('Content-Range', 'bytes 8-25/26')
                    self.end_headers()
                    self.wfile.write(body[8:])
        server = HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                destination = pathlib.Path(directory) / 'firmware'
                url = 'http://127.0.0.1:%d/input' % server.server_port
                digest = hashlib.sha256(body).hexdigest()
                try:
                    acquire(url, destination, digest)
                except (ConnectionError, ValueError):
                    pass
                partial = destination.with_suffix('.part')
                self.assertTrue(partial.is_file(), 'A short HTTP response must retain its resumable prefix')
                self.assertEqual(partial.read_bytes(), body[:8])
                self.assertFalse(destination.exists())
                acquire(url, destination, digest)
                self.assertEqual(calls, [None, 'bytes=8-'])
                self.assertEqual(destination.read_bytes(), body)
                self.assertFalse(partial.exists())
        finally:
            server.shutdown()
            worker.join(timeout=3)
            server.server_close()

    def test_unsatisfiable_corrupt_partial_restarts_with_full_request(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'firmware'
            path.with_suffix('.part').write_bytes(b'too long corrupted partial')
            calls = []
            def opener(request):
                calls.append(request.get_header('Range'))
                if len(calls) == 1:
                    raise urllib.error.HTTPError(request.full_url, 416, 'range', {}, None)
                return Response(b'COMPLETE')
            acquire('https://example.invalid/file', path, hashlib.sha256(b'COMPLETE').hexdigest(), opener=opener)
            self.assertEqual(calls, ['bytes=26-', None])
            self.assertEqual(path.read_bytes(), b'COMPLETE')

    def test_complete_partial_after_process_death_is_verified_without_range_request(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'firmware'
            path.with_suffix('.part').write_bytes(b'COMPLETE')
            def offline(request):
                raise AssertionError('A complete verified partial must not contact the server')
            acquire('https://example.invalid/file', path, hashlib.sha256(b'COMPLETE').hexdigest(), opener=offline)
            self.assertEqual(path.read_bytes(), b'COMPLETE')

    def test_full_response_to_range_request_restarts_instead_of_appending(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'firmware'
            path.with_suffix('.part').write_bytes(b'old partial')
            acquire('https://example.invalid/file', path, hashlib.sha256(b'COMPLETE').hexdigest(),
                    opener=lambda request: Response(b'COMPLETE'))
            self.assertEqual(path.read_bytes(), b'COMPLETE')

    def test_checksum_failure_never_replaces_previous_verified_input(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'firmware'
            path.write_bytes(b'old valid')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                acquire('https://example.invalid/file', path, '0' * 64,
                        opener=lambda request: Response(b'corrupt'))
            self.assertEqual(path.read_bytes(), b'old valid')

    def test_cancelled_download_does_not_promote_partial_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / 'firmware'
            with self.assertRaises(InterruptedError):
                acquire('https://example.invalid/file', path, '0' * 64,
                        cancelled=lambda: True, opener=lambda request: Response(b'anything'))
            self.assertFalse(path.exists())

    def test_incomplete_restore_cannot_replace_working_install(self):
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d)
            old = base / 'current'; old.mkdir(); (old / 'root').write_bytes(b'working')
            stage = base / 'staging'; stage.mkdir(); (stage / 'root').write_bytes(b'incomplete')
            with self.assertRaisesRegex(ValueError, 'receipt'):
                promote(stage, old)
            self.assertEqual((old / 'root').read_bytes(), b'working')
