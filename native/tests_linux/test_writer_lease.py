"""Execute the actual Linux/Android writer constructor with independent processes."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

class WriterLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.library = self.base / 'lease.so'
        self.lock = self.base / 'writer.lock'
        self.marker = self.base / 'entered-main'
        source = Path(__file__).resolve().parents[1] / 'writer-lease.c'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-o', str(self.library), str(source)], check=True)
        helper = self.base / 'helper.c'
        helper.write_text('#include <stdio.h>\n#include <unistd.h>\nint main(int n,char **v){FILE *f=fopen(v[1],"w");fprintf(f,"%d",getpid());fclose(f);for(;;)pause();}\n')
        self.helper = self.base / 'helper'
        subprocess.run(['cc', str(helper), '-o', str(self.helper)], check=True)
        self.children = []
    def tearDown(self):
        for process in self.children:
            if process.poll() is None: process.kill()
            process.wait()
        self.temp.cleanup()
    def launch(self, parent=None):
        env = dict(os.environ, LD_PRELOAD=str(self.library), IOSVM_WRITER_LOCK=str(self.lock),
                   IOSVM_WRITER_PARENT=str(os.getpid() if parent is None else parent))
        child = subprocess.Popen([str(self.helper), str(self.marker)], env=env)
        self.children.append(child)
        return child
    def wait_main(self):
        deadline = time.monotonic() + 2
        while not self.marker.exists() and time.monotonic() < deadline: time.sleep(.01)
        self.assertTrue(self.marker.exists())
    def rejected(self, process):
        try: code = process.wait(timeout=.4)
        except subprocess.TimeoutExpired:
            self.fail('Unowned writer entered main instead of being rejected')
        self.assertEqual(75, code)
        self.assertFalse(self.marker.exists())
    def test_constructor_holds_the_lock_until_real_process_exit(self):
        child = self.launch(); self.wait_main()
        with self.lock.open('a+b') as probe:
            with self.assertRaises(BlockingIOError): fcntl.lockf(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            child.terminate(); child.wait(timeout=2)
            fcntl.lockf(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def test_busy_writer_is_rejected_before_main(self):
        with self.lock.open('a+b') as owner:
            fcntl.lockf(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.rejected(self.launch())
    def test_dead_parent_identity_is_rejected_before_main(self):
        self.rejected(self.launch(parent=os.getpid() + 1))
    def test_parent_death_releases_writer_only_after_termination(self):
        launcher = self.base / 'parent.py'
        launcher.write_text('import os,subprocess,time\ne=dict(os.environ,LD_PRELOAD=' + repr(str(self.library)) +
            ',IOSVM_WRITER_LOCK=' + repr(str(self.lock)) + ',IOSVM_WRITER_PARENT=str(os.getpid()))\n' +
            'p=subprocess.Popen([' + repr(str(self.helper)) + ',' + repr(str(self.marker)) + '],env=e)\n' +
            'time.sleep(30)\n')
        parent = subprocess.Popen(['python3', str(launcher)]); self.children.append(parent)
        self.wait_main()
        child_pid = int(self.marker.read_text())
        try:
            with self.lock.open('a+b') as probe:
                with self.assertRaises(BlockingIOError): fcntl.lockf(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                parent.kill(); parent.wait()
                deadline = time.monotonic() + 2
                while True:
                    try: fcntl.lockf(probe, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                    except BlockingIOError:
                        if time.monotonic() >= deadline: self.fail('Orphan writer kept running')
                        time.sleep(.01)
        finally:
            try: os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError: pass

if __name__ == '__main__': unittest.main(verbosity=2)
