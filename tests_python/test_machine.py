from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from iosvm.installer import Machine
from iosvm.native_runtime import environment


class MachineConsoleTests(unittest.TestCase):
    def test_writer_environment_names_global_ownership_and_actual_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'libios_coroutines.so').write_bytes(b'test-only library placeholder')
            result = environment(base, base / 'stage', base)
            self.assertEqual(str(base / 'native-writer.lock'), result['IOSVM_WRITER_LOCK'])
            self.assertEqual(str(os.getpid()), result['IOSVM_WRITER_PARENT'])
            self.assertEqual(str(base / 'libios_coroutines.so'), result['LD_PRELOAD'])

    def test_quiet_live_guest_final_marker_is_reported_before_process_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('iosvm.native_runtime.environment', return_value=dict(os.environ)):
                machine = Machine([sys.executable, '-c',
                    "import time; print('FINAL PATCH MARKER', flush=True); time.sleep(30)"],
                    Path(directory), 'console.log')
            try:
                deadline = time.monotonic() + 1.5
                while 'FINAL PATCH MARKER' not in machine.console and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIn('FINAL PATCH MARKER', machine.console)
                self.assertIsNone(machine.process.poll())
            finally:
                machine.stop()
