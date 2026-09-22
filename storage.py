"""Atomic local snapshots with one prior valid generation and a process lock."""
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime
from engine import PetEngine

SAVE_ERRORS = (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError)


class PetStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "memory.json"
        self.backup = self.directory / "memory.backup.json"

    @staticmethod
    def read(path):
        if path.stat().st_size > 8_000_000:
            raise ValueError("Pet save is unexpectedly large.")
        data = json.loads(path.read_text(encoding="utf-8"))
        return PetEngine.from_dict(data)

    def load(self):
        errors = []
        for path in (self.path, self.backup):
            if path.exists():
                try:
                    engine = self.read(path)
                    warning = "主存档不可用，已恢复上一份备份。" if path == self.backup else ""
                    return engine, warning
                except SAVE_ERRORS as error:
                    errors.append(type(error).__name__)
        if errors:
            return PetEngine(), "已有存档无法读取；原文件会被保留，当前从新状态启动。"
        return PetEngine(), ""

    @staticmethod
    def atomic_write(path, text):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                             prefix=".writing-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()  # only the known temporary created by this call

    def save(self, engine):
        document = engine.to_dict()
        PetEngine.from_dict(document)  # fail before replacing any existing save
        text = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if self.path.exists():
            try:
                self.read(self.path)
            except SAVE_ERRORS:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                shutil.copy2(self.path, self.directory / f"memory.damaged-{timestamp}.json")
            else:
                if self.backup.exists():
                    try:
                        self.read(self.backup)
                    except SAVE_ERRORS:
                        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                        shutil.copy2(self.backup, self.directory / f"memory.damaged-backup-{timestamp}.json")
                self.atomic_write(self.backup, self.path.read_text(encoding="utf-8"))
        self.atomic_write(self.path, text)


class InstanceLock:
    """Keep separate app instances from overwriting the same memory directory."""
    def __init__(self, directory):
        self.path = Path(directory) / "instance.lock"
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError("小果已经在运行。请右键桌面上的小果打开控制面板。") from None
        self.handle = handle

    def release(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None
