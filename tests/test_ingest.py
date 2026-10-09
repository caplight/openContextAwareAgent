"""文档摄入测试：chunk id 稳定性 / 切分逻辑。"""

from __future__ import annotations

from enterprise_kb.ingest import _chunk_id, load_and_split


def test_chunk_id_stable_and_unique():
    assert _chunk_id("hello") == _chunk_id("hello")
    assert _chunk_id("hello") != _chunk_id("world")


def test_load_and_split_markdown(tmp_path):
    (tmp_path / "doc.md").write_text("第一段内容。\n\n第二段内容。" * 100, encoding="utf-8")
    chunks = load_and_split(tmp_path)
    assert len(chunks) > 0
    for c in chunks:
        assert set(c) == {"id", "text", "meta"}
        assert c["meta"]["source"] == "doc.md"


def test_load_and_split_empty_dir(tmp_path):
    assert load_and_split(tmp_path) == []


def test_load_and_split_unsupported_ext_skipped(tmp_path):
    (tmp_path / "doc.md").write_text("内容。" * 50, encoding="utf-8")
    (tmp_path / "ignore.bin").write_bytes(b"\x00\x01")
    chunks = load_and_split(tmp_path)
    # 只摄入 .md，跳过 .bin
    assert all(c["meta"]["source"] == "doc.md" for c in chunks)
