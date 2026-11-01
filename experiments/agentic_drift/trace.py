"""Append-only events and content-addressed artifact snapshots."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class Trace:
    def __init__(self, run_dir, workspace, secrets=()):
        self.root = Path(run_dir)
        self.workspace = Path(workspace)
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.secrets = tuple(s for s in secrets if s)
        self.sequence = 0

    def redact(self, value):
        if isinstance(value, dict):
            return {self.redact(str(key)): self.redact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(item) for item in value]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        text = str(value)
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return text

    def event(self, kind, **fields):
        self.sequence += 1
        record = self.redact(dict(sequence=self.sequence, kind=kind,
                                 timestamp=datetime.now(timezone.utc).isoformat(), **fields))
        with (self.root / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return self.sequence

    def snapshot(self, label):
        files = {}
        for path in sorted(self.workspace.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.workspace)
            if any(p in {".git", "__pycache__", ".venv"} for p in relative.parts):
                continue
            content = path.read_bytes()
            # Credentials must never enter artifact blobs.
            for secret in self.secrets:
                content = content.replace(secret.encode(), b"[REDACTED]")
            digest = hashlib.sha256(content).hexdigest()
            blob = self.root / "blobs" / digest
            blob.parent.mkdir(exist_ok=True)
            if not blob.exists():
                blob.write_bytes(content)
            files[str(relative)] = {"sha256": digest, "bytes": len(content)}
        seq = self.event("snapshot", label=label, files=files,
                         prose_semantics="unassessed")
        dump(self.root / "snapshots" / f"{seq:05d}.json", files)
        return files
