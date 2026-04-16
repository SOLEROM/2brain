import pytest
from src.utils import slug_from_title, hash8, now_iso, atomic_write
from pathlib import Path
import tempfile, os

def test_slug_basic():
    assert slug_from_title("VOXL 2 NNAPI Benchmark Notes") == "voxl-2-nnapi-benchmark-notes"

def test_slug_punctuation():
    assert slug_from_title("Hailo-8: INT8 vs FP16 Report") == "hailo-8-int8-vs-fp16-report"

def test_slug_max_length():
    long = "a " * 40  # 80 chars
    result = slug_from_title(long)
    assert len(result) <= 60

def test_slug_collapse_hyphens():
    assert slug_from_title("hello  world--test") == "hello-world-test"

def test_slug_lowercase():
    assert slug_from_title("UPPER CASE") == "upper-case"

def test_hash8_length():
    h = hash8("https://example.com/post")
    assert len(h) == 8
    assert h.isalnum()

def test_hash8_deterministic():
    h1 = hash8("test content")
    h2 = hash8("test content")
    assert h1 == h2

def test_hash8_different_inputs():
    assert hash8("a") != hash8("b")

def test_now_iso_format():
    ts = now_iso()
    import re
    assert re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', ts)

def test_atomic_write(tmp_path):
    target = tmp_path / "output.md"
    atomic_write(target, "# Hello\n")
    assert target.read_text() == "# Hello\n"

def test_atomic_write_overwrites(tmp_path):
    target = tmp_path / "output.md"
    atomic_write(target, "first")
    atomic_write(target, "second")
    assert target.read_text() == "second"

def test_atomic_write_no_tmp_left(tmp_path):
    target = tmp_path / "output.md"
    atomic_write(target, "content")
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0
