"""Durable publication receipts and small archives, independent of video caches."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

RECEIPT_NAME = 'publication.json'
VIDEO_ID_RE = re.compile(r'[A-Za-z0-9_-]{11}')
ARTIFACT_SUFFIXES = {'.txt', '.md', '.json', '.srt', '.ass', '.png', '.jpg', '.jpeg'}
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def metadata_hash(meta: dict) -> str:
    # Thumbnail changes can be retried against the same video. Moving local
    # files does not change the remote metadata or the video's identity.
    body = {k: v for k, v in meta.items() if k not in {'video_path', 'thumbnail_path'}}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        Path(name).unlink(missing_ok=True)


def save(project: Path, receipt: dict) -> None:
    atomic_bytes(project / RECEIPT_NAME, json.dumps(receipt, ensure_ascii=False, indent=2).encode())


def load(project: Path) -> dict | None:
    path = project / RECEIPT_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise ValueError(f'invalid publication receipt {path}: {e}') from e
    if not isinstance(data, dict) or data.get('status') not in {'uploading', 'uploaded', 'complete'}:
        raise ValueError(f'invalid publication receipt {path}: unknown status')
    if not isinstance(data.get('channel_id'), str) or not data['channel_id']:
        raise ValueError(f'invalid publication receipt {path}: missing channel_id')
    if data['status'] != 'uploading':
        if not isinstance(data.get('video_id'), str) or not VIDEO_ID_RE.fullmatch(data['video_id']):
            raise ValueError(f'invalid publication receipt {path}: missing/invalid video_id')
        uploaded_time(data)
    return data


def uploaded_time(receipt: dict) -> float:
    try:
        dt = datetime.fromisoformat(receipt['uploaded_at'].replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('timezone required')
        return dt.timestamp()
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError('invalid publication receipt uploaded_at') from e


@contextmanager
def locked(project: Path):
    """OS lock survives exceptions, but is automatically released on process exit."""
    project.mkdir(parents=True, exist_ok=True)
    with (project / '.publication.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RuntimeError(f'publication operation already running: {project}') from e
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def archive(project: Path, root: Path | None = None) -> Path:
    receipt = load(project)
    if not receipt or not receipt.get('video_id'):
        raise ValueError('cannot archive without successful upload receipt')
    root = root or project.parent.parent / 'assets' / 'publications'
    destination = root / receipt['video_id']
    # An archive cannot be placed within the disposable project.
    if destination.resolve() == project.resolve() or project.resolve() in destination.resolve().parents:
        raise ValueError('archive must live outside project')
    for path in project.iterdir():
        if path.name == RECEIPT_NAME or path.name.startswith('uploaded_'):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ARTIFACT_SUFFIXES:
            continue
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError(f'archive artifact exceeds 20 MiB; preserve manually before cleanup: {path}')
        atomic_bytes(destination / path.name, path.read_bytes())
    # Local candidates above are separate from the last verified uploaded asset.
    metadata_filename = receipt.get('metadata_filename', 'youtube_metadata.json')
    if not isinstance(metadata_filename, str) or Path(metadata_filename).name != metadata_filename:
        raise ValueError('invalid receipt metadata_filename')
    meta_path = project / metadata_filename
    if receipt.get('metadata_filename') and not meta_path.is_file():
        raise ValueError('original upload metadata missing; preserve it before cleanup')
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        if metadata_hash(meta) == receipt.get('metadata_sha256'):
            atomic_bytes(destination / 'uploaded_metadata.json', meta_path.read_bytes())
        thumbnail = Path(meta.get('thumbnail_path', ''))
        if (thumbnail.is_file() and receipt.get('thumbnail_status') == 'complete'
                and file_hash(thumbnail) == receipt.get('thumbnail_sha256')):
            if thumbnail.stat().st_size > MAX_ARTIFACT_BYTES:
                raise ValueError('thumbnail exceeds archive limit')
            atomic_bytes(destination / ('uploaded_thumbnail' + thumbnail.suffix), thumbnail.read_bytes())
    if receipt.get('thumbnail_sha256'):
        preserved = [p for p in destination.glob('uploaded_thumbnail.*')
                     if p.is_file() and file_hash(p) == receipt['thumbnail_sha256']]
        if not preserved:
            raise ValueError('verified uploaded thumbnail missing from archive; recover it before cleanup')
    # Write receipt last: partial archive never claims to be complete.
    save(destination, receipt)
    return destination
