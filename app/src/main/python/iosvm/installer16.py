"""Private iOS16 preparation/promotion. All entry points require the caller's DiskLease.

No iOS14 paths, downloaded executables or guest qualification claims are used here.
The additional OS-held lock excludes another Python transaction, including after a
crash. A stale journal can rename only directories whose inode identity it recorded.
"""
from contextlib import contextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import uuid

from ios16_installer.safety import Hooks, checked_path, digest
from ios16_installer.persistence import validate_data_store, STORE_BYTES, _mark_sparse

PROFILE = 'ios16.5-20F66-virt-cpu-v1'
IMMUTABLE = ('Image', 'payload.bin', 'system.apfs')
JOURNAL = 'ios16-promotion.json'
PREPARATION = 'ios16-preparation'
CURRENT = 'ios16-current'
_LOCAL = threading.Lock()


def _base(value):
    path = Path(value)
    if path.is_symlink(): raise ValueError('Private installation base is a symlink')
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _sync_dir(path):
    if os.name == 'nt': return  # Windows host tests; Android uses directory fsync.
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try: os.fsync(fd)
    finally: os.close(fd)


def _atomic_json(path, value):
    path = checked_path(path.parent, path.name)
    temporary = checked_path(path.parent, path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as out:
        json.dump(value, out, sort_keys=True, indent=2); out.write('\n')
        out.flush(); os.fsync(out.fileno())
    os.replace(temporary, path); _sync_dir(path.parent)


def _json(path):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 65536:
        raise ValueError('Invalid or oversized private receipt/journal')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict): raise ValueError('Private receipt/journal must be an object')
    return value


@contextmanager
def integration_lock(base):
    if not _LOCAL.acquire(blocking=False): raise RuntimeError('iOS16 integration owner is active')
    stream = None
    try:
        base = _base(base); path = checked_path(base, '.ios16-integration.lock')
        stream = path.open('a+b')
        if stream.tell() == 0: stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error: raise RuntimeError('iOS16 integration owner is active') from error
        yield
    finally:
        if stream is not None: stream.close()  # OS releases the lock on close/process death.
        _LOCAL.release()


def _pid_alive(pid):
    if os.name == 'nt':
        # os.kill(pid, 0) is not a safe existence probe on Windows.
        import ctypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.restype = ctypes.c_void_p
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87: return False
            raise RuntimeError('Cannot establish stale preparation owner identity')
        try:
            code = ctypes.c_uint32()
            if not api.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                raise RuntimeError('Cannot query preparation owner')
            return code.value == 259
        finally: api.CloseHandle(ctypes.c_void_p(handle))
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False
    except PermissionError: return True


def reclaim_stale_preparation_lock(base):
    """Caller owns integration lock and Java DiskLease. Never delete live/ambiguous locks."""
    base = _base(base); lock = checked_path(base, PREPARATION + '/.ios16-preparation.lock')
    if not lock.exists(): return
    if not lock.is_file() or lock.stat().st_size > 64: raise ValueError('Unknown preparation lock owner')
    text = lock.read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[0-9]{1,10}', text) or not 1 < int(text) <= 2147483647:
        raise ValueError('Unknown preparation lock owner')
    if _pid_alive(int(text)): raise RuntimeError('Preparation owner is still active')
    lock.unlink(); _sync_dir(lock.parent)
    # Leave old runs intact: a surviving extraction child may still own its old private run.


def _identity(path):
    if not path.exists(): return None
    if path.is_symlink() or not path.is_dir(): raise ValueError('Directory identity is not a private directory')
    info = path.stat(); return [info.st_dev, info.st_ino]


def verify_final(directory, hooks=None, hashes=True):
    hooks = hooks or Hooks(); hooks.check()
    directory = Path(directory)
    _identity(directory)
    required = set(IMMUTABLE) | {'data.store', 'installation.json'}
    if {path.name for path in directory.iterdir()} != required:
        raise ValueError('Prepared iOS16 directory has unexpected/missing files')
    receipt = _json(checked_path(directory, 'installation.json'))
    if (receipt.get('schema_version') != 1 or receipt.get('profile') != PROFILE or
        receipt.get('prepared') is not True or receipt.get('kernel_patches_verified') is not True):
        raise ValueError('Prepared receipt profile/status differs')
    records = receipt.get('files', {})
    if not isinstance(records, dict): raise ValueError('Invalid immutable file records')
    for name in IMMUTABLE:
        hooks.check(); path = checked_path(directory, name); record = records.get(name, {})
        if (not isinstance(record, dict) or not path.is_file() or type(record.get('bytes')) is not int or record['bytes'] <= 0 or
            path.stat().st_size != record['bytes'] or
            not isinstance(record.get('sha256'), str) or
            not re.fullmatch('[0-9a-f]{64}', record.get('sha256', ''))):
            raise ValueError('Immutable file record/size differs: ' + name)
        if hashes and digest(path, 'sha256', hooks) != record['sha256']:
            raise ValueError('Immutable SHA256 differs: ' + name)
    record = records.get('data.store', {})
    if (not isinstance(record, dict) or record.get('bytes') != STORE_BYTES or record.get('mutable') is not True or
        record.get('sha256_is_initial_only') is not True or
        not isinstance(record.get('sha256'), str) or
        not re.fullmatch('[0-9a-f]{64}', record.get('sha256', ''))):
        raise ValueError('Mutable data record is missing/invalid')
    validate_data_store(checked_path(directory, 'data.store'))
    return receipt


def _sparse_copy(source, destination, hooks):
    before = source.stat(); source_hash = hashlib.sha256(); position = 0
    zeros = bytes(1024 * 1024)
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        _mark_sparse(outgoing.fileno())
        while True:
            hooks.check(); data = incoming.read(len(zeros))
            if not data: break
            source_hash.update(data)
            if data != zeros[:len(data)]: outgoing.seek(position); outgoing.write(data)
            position += len(data)
        outgoing.truncate(position); outgoing.flush(); os.fsync(outgoing.fileno())
    after = source.stat()
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or
        position != STORE_BYTES or digest(destination, 'sha256', hooks) != source_hash.hexdigest()):
        raise ValueError('Preserved data copy failed full readback verification')


def _preserve_data(current, stage, receipt, hooks):
    if not current.exists(): return receipt
    _identity(current); source = checked_path(current, 'data.store')
    old_receipt = None
    try: old_receipt = _json(checked_path(current, 'installation.json'))
    except (ValueError, OSError): pass  # Corrupt boot receipts do not justify discarding valid userdata.
    old_files = (old_receipt or {}).get('files', {})
    old_record = old_files.get('data.store') if isinstance(old_files, dict) else None
    if not source.exists():
        if old_record is not None: raise ValueError('Previously recorded data.store is missing; refusing fresh reset')
        return receipt
    validate_data_store(source); hooks.check()
    temporary = checked_path(stage, 'data-preserved-' + uuid.uuid4().hex)
    method = 'hardlink'
    try:
        try: os.link(source, temporary)
        except OSError:
            method = 'sparse_copy'; _sparse_copy(source, temporary, hooks)
        validate_data_store(temporary); hooks.check()
        os.replace(temporary, checked_path(stage, 'data.store')); _sync_dir(stage)
    finally:
        temporary.unlink(missing_ok=True)
    preserved_initial = (isinstance(old_record, dict) and old_record.get('bytes') == STORE_BYTES and
        old_record.get('mutable') is True and old_record.get('sha256_is_initial_only') is True and
        isinstance(old_record.get('sha256'), str) and
        re.fullmatch('[0-9a-f]{64}', old_record.get('sha256', '')) is not None and
        (old_receipt or {}).get('profile') == PROFILE)
    if preserved_initial:
        receipt['files']['data.store'] = dict(old_record)
    else:
        receipt['files']['data.store'] = {'bytes': STORE_BYTES, 'mutable': True,
            'sha256_is_initial_only': True, 'sha256': digest(source, 'sha256', hooks),
            'sha256_origin': 'preserved archive snapshot at repair import; creation provenance unavailable'}
    receipt['data_preservation'] = {'method': method, 'bytes': STORE_BYTES,
        'initial_sha256_preserved': preserved_initial,
        'shared_inode_with_previous': method == 'hardlink'}
    return receipt


def _retire(base):
    checked_path(base, JOURNAL).unlink(); _sync_dir(base)


def _read_journal(base):
    data = _json(checked_path(base, JOURNAL)); token = data.get('token', '')
    if (data.get('schema_version') != 1 or data.get('profile') != PROFILE or
        not isinstance(token, str) or not re.fullmatch('[0-9a-f]{32}', token) or
        data.get('stage') != 'ios16-staging-' + token or data.get('backup') != 'ios16-previous-' + token or
        not isinstance(data.get('receipt_sha256'), str) or
        not re.fullmatch('[0-9a-f]{64}', data.get('receipt_sha256', ''))):
        raise ValueError('Invalid iOS16 promotion journal')
    for name in ('old_identity', 'new_identity'):
        value = data.get(name)
        if name == 'old_identity' and value is None: continue
        if not isinstance(value, list) or len(value) != 2 or any(type(n) is not int or n < 0 for n in value):
            raise ValueError('Invalid journal directory identity')
    return data


def _recover_locked(base):
    if not checked_path(base, JOURNAL).exists(): return None
    data = _read_journal(base)
    current = checked_path(base, CURRENT); stage = checked_path(base, data['stage'])
    backup = checked_path(base, data['backup'])
    current_id, stage_id, backup_id = _identity(current), _identity(stage), _identity(backup)
    old, new = data['old_identity'], data['new_identity']
    if stage_id is not None and stage_id != new: raise ValueError('Staging directory identity differs')
    if backup_id is not None and backup_id != old: raise ValueError('Backup directory identity differs')
    if current_id == new:
        if stage_id is not None or (old is not None and backup_id != old):
            raise ValueError('Ambiguous promoted directory identity')
        try:
            verify_final(current)
            if digest(current / 'installation.json') != data['receipt_sha256']:
                raise ValueError('Promoted receipt changed')
        except (ValueError, OSError):
            damaged = checked_path(base, 'ios16-damaged-' + data['token'])
            if damaged.exists(): raise ValueError('Damaged evidence path already exists')
            os.rename(current, damaged); _sync_dir(base)
            if backup_id is not None: os.rename(backup, current); _sync_dir(base)
        _retire(base); return current if current.exists() else None
    if current_id is not None:
        if current_id != old or backup_id is not None:
            raise ValueError('Unrelated current directory identity; refusing stale journal overwrite')
        _retire(base); return current  # Crash before the first rename; old install stays selected.
    if old is not None:
        if backup_id != old: raise ValueError('Original directory identity cannot be recovered')
        os.rename(backup, current); _sync_dir(base)
    _retire(base); return current if current.exists() else None


def recover(base):
    base = _base(base)
    with integration_lock(base):
        reclaim_stale_preparation_lock(base)
        return _recover_locked(base)


def _promote_locked(base, prepared, hooks, checkpoint):
    prepared = Path(prepared)
    if any(path.is_symlink() for path in (prepared, *prepared.parents)):
        raise ValueError('Symlink in prepared directory path')
    prepared = prepared.resolve()
    # The prepare API may return only its private runs/<name>/final, never another profile path.
    relative = prepared.relative_to(base).as_posix()
    if (not relative.startswith(PREPARATION + '/runs/preparation-') or prepared.name != 'final' or
        checked_path(base, relative) != prepared):
        raise ValueError('Unapproved prepared directory path')
    hooks.check(); receipt = verify_final(prepared, hooks, hashes=False)
    current = checked_path(base, CURRENT); _identity(current)
    receipt = _preserve_data(current, prepared, receipt, hooks)
    for key in ('gui_boot_verified', 'input_verified', 'persistence_verified'): receipt[key] = False
    receipt['qualification'] = 'experimental; fresh preparation is not guest device qualification'
    _atomic_json(prepared / 'installation.json', receipt)
    verify_final(prepared, hooks)  # Full SHA256 immediately before the publication transaction.
    for name in (*IMMUTABLE, 'data.store', 'installation.json'):
        with checked_path(prepared, name).open('r+b') as stream: os.fsync(stream.fileno())
    _sync_dir(prepared)
    token = uuid.uuid4().hex; stage = checked_path(base, 'ios16-staging-' + token)
    backup = checked_path(base, 'ios16-previous-' + token)
    hooks.check(); os.rename(prepared, stage); _sync_dir(prepared.parent); _sync_dir(base)
    journal = {'schema_version': 1, 'profile': PROFILE, 'token': token, 'stage': stage.name,
        'backup': backup.name, 'old_identity': _identity(current), 'new_identity': _identity(stage),
        'receipt_sha256': digest(stage / 'installation.json')}
    try:
        _atomic_json(checked_path(base, JOURNAL), journal); checkpoint('journal_ready'); hooks.check()
        if current.exists(): os.rename(current, backup); _sync_dir(base)
        checkpoint('old_moved'); hooks.check()
        os.rename(stage, current); _sync_dir(base)
        checkpoint('new_moved')
        _retire(base)
        return current
    except Exception:
        # Normal errors/cancellation roll back before publication. Process death leaves the journal.
        _recover_locked(base)
        raise


def promote(base, prepared, hooks=None, checkpoint=lambda phase: None):
    base = _base(base)
    with integration_lock(base):
        _recover_locked(base)
        return _promote_locked(base, prepared, hooks or Hooks(), checkpoint)


def install(files_dir, native_dir, resources_dir, callback, *, prepare_fn=None):
    """Called only by the nonexported foreground InstallService while it holds DiskLease."""
    base = _base(files_dir); resources = Path(resources_dir)
    hooks = Hooks(cancelled=lambda: bool(callback.isCancelled()),
                  progress=lambda message, fraction: callback.update(str(message), float(fraction)))
    with integration_lock(base):
        reclaim_stale_preparation_lock(base); _recover_locked(base); hooks.check()
        manifest = _json(checked_path(resources, 'resource-manifest.json'))
        if manifest.get('profile') != PROFILE or manifest.get('persistence') is not True:
            raise ValueError('iOS16 integration requires the pinned persistent resource manifest')
        if prepare_fn is None:
            from ios16_installer import prepare as prepare_fn
        final = prepare_fn(checked_path(base, PREPARATION), manifest,
            checked_path(resources, 'assets'), Path(native_dir), hooks)
        hooks.report('Verifying and promoting private iOS16 installation', 0)
        result = _promote_locked(base, Path(final), hooks, lambda phase: None)
        # Publication has committed; a later cancel cannot turn success into an apparent failure.
        callback.update('Experimental iOS16 preparation complete; device qualification pending', 1.0)
        return str(result)


def sqlite_smoke(base):
    """Instrumentation-only real sqlite3/_sqlite3 private transaction, no guest data."""
    import sqlite3
    import _sqlite3
    base = _base(base)
    database = checked_path(base, 'ios16-sqlite-smoke-' + uuid.uuid4().hex + '.sqlite')
    descriptor = os.open(str(database), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(str(database))) as connection:
            connection.execute('PRAGMA journal_mode=DELETE')
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE smoke(id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
            connection.execute('INSERT INTO smoke VALUES(?,?)', (1, 'private UID transaction'))
            connection.commit()
        with database.open('r+b') as stream: os.fsync(stream.fileno())
        with closing(_sqlite3.connect(str(database))) as connection:
            rows = connection.execute('SELECT id,value FROM smoke').fetchall()
        if rows != [(1, 'private UID transaction')]: raise ValueError('SQLite transaction readback differs')
        return json.dumps({'transaction_verified': True, 'native_extension_loaded': True,
            'rows': len(rows), 'sqlite_version': _sqlite3.sqlite_version,
            'uid': os.getuid() if hasattr(os, 'getuid') else None})
    finally:
        for suffix in ('', '-journal', '-wal', '-shm'):
            checked_path(base, database.name + suffix).unlink(missing_ok=True)
