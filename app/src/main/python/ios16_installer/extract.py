"""Selected-file 7zz extraction. Guest links remain metadata, never host symlinks."""
import os
from contextlib import contextmanager
from pathlib import Path
import shutil
import sqlite3
import stat
import struct
import subprocess
import tempfile
import threading
import time
from .safety import Hooks, Row, safe_relative, checked_path
from .vendor import select_system, font_trim

# The pinned official 20F66 rootfs listing from Linux 7zz26.05 is204,474,374
# bytes /318,098 entries. These are disk-output bounds with verified headroom,
# not an allowance to load the listing or every unselected inode into RAM.
MAX_LISTING = 256 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 400000
MAX_SELECTED_ROWS = 100000
MAX_VAR_ROWS = 20000

def run_tool(argv, output, hooks, accepted=(0,), max_bytes=MAX_LISTING):
    """No shell; bounded disk log; cancellation terminates and reaps the one child."""
    hooks.check()
    with open(output, 'wb') as log:
        process = subprocess.Popen([str(value) for value in argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL)
        exceeded = threading.Event(); errors = []
        def drain():
            total = 0
            try:
                while True:
                    chunk = process.stdout.read(65536)
                    if not chunk: break
                    permitted = min(len(chunk), max(0, max_bytes - total))
                    log.write(chunk[:permitted]); total += len(chunk)
                    if total > max_bytes: exceeded.set(); break
            except Exception as error: errors.append(error)
        reader = threading.Thread(target=drain, daemon=True); reader.start()
        try:
            while process.poll() is None:
                hooks.check()
                if exceeded.is_set() or errors:
                    raise ValueError('Native tool output exceeds limit')
                time.sleep(.1)
            reader.join(timeout=3)
            if reader.is_alive() or exceeded.is_set() or errors or process.returncode not in accepted:
                raise ValueError('Native tool failed; inspect private installer log')
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
            reader.join(timeout=3); process.stdout.close()
        return process.returncode

def listing_entries(listing):
    """One bounded record at a time; even a malformed single line stays bounded."""
    with open(listing, encoding='utf-8', errors='strict') as stream:
        entry = {}; duplicates = set(); inodes = False; unstructured = False
        while True:
            line = stream.readline(65538)
            if len(line) > 65536: raise ValueError('Oversized listing line')
            eof = not line
            line = line.rstrip('\r\n')
            if not line or line in ('--','----','----------'):
                if 'Mode' in entry:
                    if 'Path' not in entry or duplicates or unstructured: raise ValueError('Malformed or duplicate inode fields')
                    inodes = True; yield entry
                elif inodes and 'Path' in entry: raise ValueError('Inode mode is absent')
                entry = {}; duplicates = set(); unstructured = False
                if eof: break
            elif ' = ' in line or line.endswith(' ='):
                key, _, value = line.partition(' =')
                if key in entry: duplicates.add(key)
                entry[key] = value[1:] if value.startswith(' ') else value
                if len(entry) > 64: raise ValueError('Oversized listing record')
            elif 'Path' in entry: unstructured = True

def archive_relative(path):
    """Validate POSIX archive metadata; colons are legal in excluded Apple names.

    Host extraction paths still pass safe_relative after selection. In particular,
    the official excluded WorkflowKit localizations contain five colon names;
    they must not make the whole image fail before selection.
    """
    if (not isinstance(path,str) or not path or path.startswith(('/', '-', '@')) or '\\' in path or
        any(ord(c)<32 or ord(c)==127 for c in path) or len(path.encode('utf-8'))>4096 or
        any(part in ('','.','..') for part in path.split('/'))):
        raise ValueError('Unsafe archive path')
    return path

def parsed_row(entry):
    import re
    text = entry.get('Mode','')
    if not re.fullmatch(r'[-dl][r-][w-][xsS-][r-][w-][xsS-][r-][w-][xtT-]', text):
        raise ValueError('Invalid archive mode')
    mode = select_system.mode_bits(text); path = archive_relative(entry['Path'])
    uid, gid = int(entry.get('User ID') or 0), int(entry.get('Group ID') or 0)
    if not 0 <= uid < 2**32 or not 0 <= gid < 2**32: raise ValueError('Invalid archive owner')
    target = entry.get('Symbolic Link','')
    if (any(ord(c)<32 or ord(c)==127 for c in target) or len(target.encode('utf-8'))>4096 or
        stat.S_ISLNK(mode) and not target): raise ValueError('Invalid symlink data')
    size = int(entry.get('Size') or 0)
    if not 0 <= size < 8*1024**3: raise ValueError('Archive file size exceeds limit')
    return Row(mode,uid,gid,path,target),size

@contextmanager
def indexed_listing(listing,hooks):
    """Validate all paths/ancestors using a disposable disk index, not a RAM set."""
    listing=Path(listing)
    if listing.stat().st_size > MAX_LISTING: raise ValueError('Listing exceeds limit')
    with tempfile.TemporaryDirectory(prefix='listing-index-',dir=listing.parent) as temp:
        db=sqlite3.connect(str(Path(temp)/'paths.sqlite'))
        try:
            db.execute('PRAGMA cache_size=-2048')
            db.execute('PRAGMA mmap_size=0')
            db.execute('PRAGMA temp_store=FILE')
            db.execute('PRAGMA journal_mode=OFF')
            db.execute('CREATE TABLE entries(path TEXT PRIMARY KEY,mode INTEGER,uid INTEGER,gid INTEGER,target TEXT,size INTEGER,zbm INTEGER) WITHOUT ROWID')
            db.execute('CREATE TABLE parents(path TEXT PRIMARY KEY) WITHOUT ROWID')
            for number,entry in enumerate(listing_entries(listing),1):
                hooks.check()
                if number>MAX_ARCHIVE_ENTRIES: raise ValueError('Archive entry limit exceeded')
                row,size=parsed_row(entry)
                try: db.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?)',(row.path,row.mode,row.uid,row.gid,row.target,size,int(entry.get('Method')=='ZBM-rsrc')))
                except sqlite3.IntegrityError as error: raise ValueError('Duplicate archive path') from error
                parent=row.path.rpartition('/')[0]
                while parent:
                    db.execute('INSERT OR IGNORE INTO parents VALUES(?)',(parent,))
                    parent=parent.rpartition('/')[0]
            if db.execute('SELECT e.path FROM entries e JOIN parents p ON p.path=e.path WHERE (e.mode & ?)!=? LIMIT 1',
                          (stat.S_IFMT(0o177777),stat.S_IFDIR)).fetchone():
                raise ValueError('Archive traverses a non-directory')
            db.commit();yield db
        finally: db.close()

def listing_rows(listing):
    """Compatibility helper for small callers/tests; preparation uses selected_listing."""
    with indexed_listing(listing,Hooks()) as db:
        rows=[];sizes={}
        for path,mode,uid,gid,target,size,_ in db.execute('SELECT * FROM entries ORDER BY path'):
            rows.append(Row(mode,uid,gid,path,target));sizes[path]=size
        return rows,sizes

def root_keep(path,mode,size):
    import re
    if stat.S_ISREG(mode): return select_system.wanted_file(path,size)
    if stat.S_ISLNK(mode): return '/' not in path or path.startswith(select_system.WHOLE) and not path.startswith(select_system.SKIP_PREFIX)
    language=re.search(r'/([^/]+)\.lproj$',path)
    return ('/' not in path or path in ('private/var','private/tmp','private/etc','private/preboot','private/xarts','private') or
            bool(language) and language.group(1) in select_system.KEEP_LANG and
            (path.startswith(select_system.WHOLE) and not path.startswith(select_system.SKIP_PREFIX) or
             path.startswith(select_system.AUDIO) and not path.startswith(select_system.SKIP_AUDIO)))

def selected_listing(listing,hooks=None,root=False,os_cryptex=False,zbm_paths=None):
    """Return only selected rows/sources/sizes plus root /private/var skeleton rows."""
    hooks=hooks or Hooks()
    with indexed_listing(listing,hooks) as db:
        db.execute('CREATE TABLE destinations(path TEXT PRIMARY KEY,source TEXT,staged INTEGER,keep INTEGER) WITHOUT ROWID')
        db.execute('CREATE TABLE chosen(path TEXT PRIMARY KEY) WITHOUT ROWID')
        var_rows=[]
        for path,mode,uid,gid,target,size,_ in db.execute('SELECT * FROM entries ORDER BY path'):
            hooks.check();dest=path;staged=False
            if root:
                if (path=='private/var' or path.startswith('private/var/')) and not path.startswith(
                    ('private/var/staged_system_apps','private/var/MobileAsset/')) and not stat.S_ISREG(mode):
                    var_rows.append(Row(mode,uid,gid,path,target))
                    if len(var_rows)>MAX_VAR_ROWS: raise ValueError('Data skeleton entry limit exceeded')
                if path.startswith(select_system.STAGED_APPS):
                    dest='Applications/'+path[len(select_system.STAGED_APPS):];staged=True
                elif path.startswith('private/var/'): continue
                keep=root_keep(dest,mode,size)
            else:
                keep=not os_cryptex or not (path=='System/DriverKit' or path.startswith('System/DriverKit/') or '.symbols' in path)
            # A staged application replaces its root stub regardless of inode order.
            db.execute('INSERT INTO destinations VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET '
                       'source=excluded.source,staged=excluded.staged,keep=excluded.keep WHERE excluded.staged>=destinations.staged',
                       (dest,path,int(staged),int(bool(keep))))
        for (path,) in db.execute('SELECT path FROM destinations WHERE keep=1'):
            hooks.check()
            while path:
                db.execute('INSERT OR IGNORE INTO chosen VALUES(?)',(path,));path=path.rpartition('/')[0]
        if db.execute('SELECT COUNT(*) FROM chosen').fetchone()[0]>MAX_SELECTED_ROWS:
            raise ValueError('Selected archive entry limit exceeded')
        rows=[];sources={};sizes={}
        query=('SELECT d.path,e.path,e.mode,e.uid,e.gid,e.target,e.size,e.zbm FROM chosen c '
               'JOIN destinations d ON d.path=c.path JOIN entries e ON e.path=d.source ORDER BY d.path')
        for dest,path,mode,uid,gid,target,size,zbm in db.execute(query):
            hooks.check();safe_relative(dest);safe_relative(path)
            rows.append(Row(mode,uid,gid,dest,target));sources[dest]=path;sizes[path]=size
            if zbm and stat.S_ISREG(mode) and zbm_paths is not None:zbm_paths.add(path)
        return rows,sources,sizes,var_rows if root else rows

def unsupported_members(log,returncode,expected):
    """Only exact member errors survive the quiet 7zz error-only output channel."""
    paths=set();prefix='ERROR: Unsupported Method : '
    with open(log,encoding='utf-8',errors='strict') as source:
        while True:
            line=source.readline(65538)
            if not line:break
            if len(line)>65536:raise ValueError('Oversized extraction error line')
            line=line.rstrip('\r\n')
            if not line:continue
            if not line.startswith(prefix):raise ValueError('Unexpected native extraction error')
            path=safe_relative(line[len(prefix):])
            if path not in expected or path in paths:raise ValueError('Unexpected or duplicate unsupported member')
            paths.add(path)
    if returncode not in (0,2) or (returncode==2)!=bool(paths):
        raise ValueError('Extraction exit status has no matching recoverable member errors')
    return paths

def validate_decmpfs14(base,expected_size):
    """Bind the two regular sidecars to this selected member before invoking unzbm."""
    header=Path(str(base)+':com.apple.decmpfs');fork=Path(str(base)+':com.apple.ResourceFork')
    for path in (base,header,fork):
        if path.is_symlink() or not path.is_file():raise ValueError('Missing or unsafe compressed member sidecar')
    if header.stat().st_size!=16 or not 0<=expected_size<=4*1024**3:
        raise ValueError('Invalid decmpfs14 header size or member bound')
    with header.open('rb') as source:magic,method,size=struct.unpack('<4sIQ',source.read(16))
    if magic!=b'fpmc' or method!=14 or size!=expected_size:raise ValueError('Compressed member header does not match listing')
    blocks=(size+65535)//65536;table_bytes=(blocks+1)*4;fork_size=fork.stat().st_size
    if fork_size<table_bytes:raise ValueError('Truncated decmpfs14 block table')
    with fork.open('rb') as source:
        first=struct.unpack('<I',source.read(4))[0];source.seek(blocks*4);last=struct.unpack('<I',source.read(4))[0]
    if not table_bytes<=first<=last<=fork_size:raise ValueError('Invalid decmpfs14 block-table bounds')

def select_root(rows, sizes):
    meta = {}; sources = {}
    for row in rows:
        path = row.path
        if path.startswith(select_system.STAGED_APPS):
            path = 'Applications/' + path[len(select_system.STAGED_APPS):]
        elif path.startswith('private/var/'): continue
        # Match the pinned recipe: a later staged-app entry replaces a root stub.
        # Duplicate original archive paths were already rejected by listing_rows.
        meta[path] = Row(row.mode, row.uid, row.gid, path, row.target); sources[path] = row.path
    chosen = set()
    import re
    for path, row in meta.items():
        if stat.S_ISREG(row.mode): keep = select_system.wanted_file(path, sizes[sources[path]])
        elif stat.S_ISLNK(row.mode):
            keep = '/' not in path or path.startswith(select_system.WHOLE) and not path.startswith(select_system.SKIP_PREFIX)
        else:
            language = re.search(r'/([^/]+)\.lproj$', path)
            keep = ('/' not in path or path in ('private/var', 'private/tmp', 'private/etc', 'private/preboot', 'private/xarts', 'private') or
                    bool(language) and language.group(1) in select_system.KEEP_LANG and
                    (path.startswith(select_system.WHOLE) and not path.startswith(select_system.SKIP_PREFIX) or
                     path.startswith(select_system.AUDIO) and not path.startswith(select_system.SKIP_AUDIO)))
        if keep: chosen.add(path)
    for path in list(chosen):
        while '/' in path: path = path.rsplit('/', 1)[0]; chosen.add(path)
    return [meta[path] for path in sorted(chosen) if path in meta], sources

def extract_image(image, directory, tools, hooks=None, root=False, os_cryptex=False):
    hooks = hooks or Hooks(); directory = Path(directory)
    if directory.is_symlink():raise ValueError('Extraction destination cannot be a symlink')
    directory.mkdir(parents=True, exist_ok=True)
    directory=directory.resolve()
    if any(directory.iterdir()): raise ValueError('Extraction destination must be empty')
    listing = directory.parent / (directory.name + '.slt')
    run_tool([tools['7zz'], 'l', '-slt', '-sccUTF-8', image], listing, hooks)
    expected_zbm=set()
    rows,sources,sizes,all_rows=selected_listing(listing,hooks,root=root,os_cryptex=os_cryptex,zbm_paths=expected_zbm)
    files = [row for row in rows if stat.S_ISREG(row.mode)]
    listfile = directory.parent / (directory.name + '.files')
    listfile.write_text(''.join(sources[row.path] + '\n' for row in files), encoding='utf-8')
    # -spd disables archive wildcard expansion; only exact validated regular-file names are passed.
    error_log=directory.parent/(directory.name+'.extract.log')
    result=run_tool([tools['7zz'], 'x', '-y', '-spd', '-mmt=2', '-snoi-', '-bso0', '-bse1', '-bsp0',
                    '-scsUTF-8', '-sccUTF-8', '-o' + str(directory), image,
                    '@' + str(listfile)], error_log, hooks, (0, 2), 8 * 1024**2)
    unsupported=unsupported_members(error_log,result,expected_zbm)
    allowed = {sources[row.path] for row in files}
    for item in directory.rglob('*'):
        hooks.check()
        if item.is_symlink(): raise ValueError('Extractor materialized a host symlink')
        if item.is_file():
            path = item.relative_to(directory).as_posix()
            if path not in allowed and not any(path == base + suffix for base in allowed
                    for suffix in (':com.apple.decmpfs', ':com.apple.ResourceFork')):
                raise ValueError('Extractor wrote an unselected file')
    compressed = [checked_path(directory, sources[row.path]) for row in files
                  if Path(str(checked_path(directory, sources[row.path])) + ':com.apple.decmpfs').is_file()]
    if {path.relative_to(directory).as_posix() for path in compressed}!=unsupported:
        raise ValueError('Unsupported member errors and compressed sidecars differ')
    for path in compressed:validate_decmpfs14(path,sizes[path.relative_to(directory).as_posix()])
    for start in range(0, len(compressed), 100):
        run_tool([tools['unzbm']] + compressed[start:start + 100],
                 directory.parent / (directory.name + '.unzbm.log'), hooks, max_bytes=1024**2)
    for path in compressed:
        if (path.stat().st_size!=sizes[path.relative_to(directory).as_posix()] or
            any(Path(str(path)+suffix).exists() for suffix in (':com.apple.decmpfs',':com.apple.ResourceFork'))):
            raise ValueError('Compressed member recovery did not finish exactly')
    for item in directory.rglob('*'):
        if ':com.apple.' in item.name: raise ValueError('Unexpanded compressed attribute remains')
    for row in files:
        hooks.check(); source = checked_path(directory, sources[row.path])
        if not source.is_file() or source.stat().st_size != sizes[sources[row.path]]:
            raise ValueError('Extracted file missing or wrong length')
    if os_cryptex:
        caches = [row for row in files if row.path.startswith('System/Library/Caches/com.apple.dyld/')]
        if len(caches) != 43: raise ValueError('Expected 43 dyld cache files')
    if root:
        emoji = checked_path(directory, 'System/Library/Fonts/CoreAddition/AppleColorEmoji-160px.ttc')
        pingfang = checked_path(directory, 'System/Library/Fonts/LanguageSupport/PingFang.ttc')
        if max(emoji.stat().st_size, pingfang.stat().st_size) > 256 * 1024**2:
            raise ValueError('Font trimming input exceeds its memory limit')
        try:
            hooks.check(); font_trim.emoji(str(emoji), str(emoji), {40, 64, 96})
            hooks.check(); font_trim.faces_of(str(pingfang), str(pingfang), r'^\.?PingFang(SC|TC|HK)-(Regular|Semibold)$')
        except SystemExit as error: raise ValueError('Pinned font trimming failed') from error
    return rows, sources, all_rows
