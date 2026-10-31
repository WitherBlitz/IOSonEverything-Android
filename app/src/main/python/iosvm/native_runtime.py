"""Environment for the narrowly scoped native QEMU context library."""
import os
from pathlib import Path


def environment(native, temporary, owner_base=None):
    library = Path(native) / 'libios_coroutines.so'
    if not library.is_file():
        raise RuntimeError('The bundled QEMU context library is missing')
    result = {**os.environ, 'TMPDIR': str(temporary), 'LD_PRELOAD': str(library)}
    if owner_base is not None:
        result.update(IOSVM_WRITER_LOCK=str(Path(owner_base) / 'native-writer.lock'),
                      IOSVM_WRITER_PARENT=str(os.getpid()))
    return result
