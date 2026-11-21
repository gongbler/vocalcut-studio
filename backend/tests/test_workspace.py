import io

import pytest

from app.storage.workspace import FileTooLargeError, Workspace


def test_save_stream_rejects_oversized(tmp_path):
    dest = tmp_path / "out.bin"
    src = io.BytesIO(b"x" * 3000)

    with pytest.raises(FileTooLargeError):
        Workspace.save_stream(src, dest, max_bytes=2000)


def test_save_stream_copies_exact_bytes(tmp_path):
    data = b"abc" * 1_000_000  # 3MB → 여러 조각(chunk)으로 나눠 복사됨
    dest = tmp_path / "out.bin"

    written = Workspace.save_stream(io.BytesIO(data), dest, max_bytes=10**8)

    assert written == len(data)
    assert dest.read_bytes() == data


def test_upload_dir_validates_id(tmp_path):
    ws = Workspace(tmp_path)
    ws.ensure()
    file_id, _ = ws.create_upload_dir()

    assert ws.upload_dir(file_id) is not None
    assert ws.upload_dir("../" + file_id) is None
    assert ws.upload_dir("not-a-real-id") is None
