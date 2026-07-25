"""P5-T05: ContentBlock cursor generator tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.document_pipeline.candidate_schema import validate_candidate_card_v2
from tools.document_pipeline.cursor_generator import (
    GENERATOR,
    PROMPT_VERSION,
    assert_full_coverage,
    load_content_blocks,
    pack_blocks,
    run_cursor_generation,
)
from tools.document_pipeline.paths import ROOT

FIXTURES = ROOT / "tools" / "document_pipeline" / "fixtures"
ZHONGYAO_BLOCKS = FIXTURES / "cursor_zhongyao_content_blocks.json"
JICHU_BLOCKS = FIXTURES / "cursor_jichu_content_blocks.json"

# Intentionally small so multi-window packing is forced.
MAX_CHARS = 180


@pytest.fixture()
def zhongyao_blocks():
    return load_content_blocks(ZHONGYAO_BLOCKS)


def test_pack_blocks_covers_all_and_respects_max_chars(zhongyao_blocks) -> None:
    total_chars = sum(len(b["cleaned_text"]) for b in zhongyao_blocks)
    assert total_chars > MAX_CHARS
    windows = pack_blocks(zhongyao_blocks, max_chars=MAX_CHARS)
    assert len(windows) >= 2
    packed_ids = [b["id"] for w in windows for b in w]
    assert packed_ids == [b["id"] for b in zhongyao_blocks]
    for window in windows:
        if len(window) == 1:
            continue
        text_len = sum(len(b["cleaned_text"]) for b in window) + 2 * (len(window) - 1)
        assert text_len <= MAX_CHARS


def test_cursor_covers_every_chunk_when_input_exceeds_max_chars(
    zhongyao_blocks, tmp_path: Path
) -> None:
    out_dir = tmp_path / "gen1"
    result = run_cursor_generation(
        zhongyao_blocks,
        book_template="zhongyao",
        document_version="zhongyao.v1.e9037a725021",
        generation_batch_id="p5t05-zhongyao-1",
        max_chars=MAX_CHARS,
        mode="offline",
        out_dir=out_dir,
        state_path=out_dir / "cursor_state.json",
    )
    assert result.windows_total >= 2
    assert result.windows_processed == result.windows_total
    assert_full_coverage(zhongyao_blocks, result.covered_chunk_ids)
    assert set(result.covered_chunk_ids) == {b["id"] for b in zhongyao_blocks}
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "candidates.jsonl").exists()
    assert (out_dir / "requests.jsonl").exists()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "candidate_only"
    assert manifest["generator"] == GENERATOR
    assert manifest["prompt_version"] == PROMPT_VERSION
    # every request records provenance fields
    for req in result.state.requests:
        assert req["chunk_ids"]
        assert req["input_hash"]
        assert req["prompt_version"] == PROMPT_VERSION
        assert "token_usage" in req
        assert "cost" in req
        assert req["status"] == "success"


def test_repeat_run_does_not_duplicate_candidates(
    zhongyao_blocks, tmp_path: Path
) -> None:
    out_dir = tmp_path / "gen-repeat"
    state_path = out_dir / "cursor_state.json"
    first = run_cursor_generation(
        zhongyao_blocks,
        book_template="zhongyao",
        document_version="zhongyao.v1.e9037a725021",
        generation_batch_id="p5t05-zhongyao-repeat",
        max_chars=MAX_CHARS,
        mode="offline",
        out_dir=out_dir,
        state_path=state_path,
    )
    second = run_cursor_generation(
        zhongyao_blocks,
        book_template="zhongyao",
        document_version="zhongyao.v1.e9037a725021",
        generation_batch_id="p5t05-zhongyao-repeat",
        max_chars=MAX_CHARS,
        mode="offline",
        out_dir=out_dir,
        state_path=state_path,
        resume=True,
    )
    assert first.windows_processed >= 1
    assert second.windows_processed == 0
    assert second.windows_skipped == second.windows_total
    assert len(second.cards) == len(first.cards)
    hashes = [c.content_hash for c in second.cards]
    assert len(hashes) == len(set(hashes))
    for card in second.cards:
        validate_candidate_card_v2(card)
        assert card.input_hash
        assert card.chunk_ids
        assert card.generator == GENERATOR


def test_resume_from_partial_cursor(zhongyao_blocks, tmp_path: Path) -> None:
    out_dir = tmp_path / "gen-resume"
    state_path = out_dir / "cursor_state.json"
    windows = pack_blocks(zhongyao_blocks, max_chars=MAX_CHARS)
    assert len(windows) >= 3

    # First run only first window by temporarily failing later via tiny subset write
    partial_blocks = [b for w in windows[:1] for b in w]
    first = run_cursor_generation(
        partial_blocks,
        book_template="zhongyao",
        document_version="zhongyao.v1.e9037a725021",
        generation_batch_id="p5t05-zhongyao-resume",
        max_chars=MAX_CHARS,
        mode="offline",
        out_dir=out_dir,
        state_path=state_path,
    )
    assert first.windows_processed == 1
    completed_before = set(first.state.completed_chunk_ids)
    assert completed_before

    # Resume over full block list; completed window skipped
    second = run_cursor_generation(
        zhongyao_blocks,
        book_template="zhongyao",
        document_version="zhongyao.v1.e9037a725021",
        generation_batch_id="p5t05-zhongyao-resume",
        max_chars=MAX_CHARS,
        mode="offline",
        out_dir=out_dir,
        state_path=state_path,
        resume=True,
    )
    assert second.windows_skipped >= 1
    assert second.windows_processed >= 1
    assert_full_coverage(zhongyao_blocks, second.state.completed_chunk_ids)
    assert completed_before.issubset(set(second.state.completed_chunk_ids))
    hashes = [c.content_hash for c in second.cards]
    assert len(hashes) == len(set(hashes))


def test_api_mode_invokes_caller_per_window_not_prefix_only(
    zhongyao_blocks, tmp_path: Path
) -> None:
    seen_chunks: list[list[str]] = []

    def fake_caller(text, *, book, model, chunk_ids, input_hash):
        seen_chunks.append(list(chunk_ids))
        # return empty candidate list; provenance still recorded
        return []

    fake_caller.last_usage = {
        "prompt_tokens": 10,
        "completion_tokens": 0,
        "total_tokens": 10,
        "cost": 0.0,
    }

    out_dir = tmp_path / "gen-api"
    result = run_cursor_generation(
        zhongyao_blocks,
        book_template="zhongyao",
        document_version="zhongyao.v1.e9037a725021",
        generation_batch_id="p5t05-api",
        max_chars=MAX_CHARS,
        mode="api",
        model="fake-qwen",
        model_caller=fake_caller,
        out_dir=out_dir,
        state_path=out_dir / "cursor_state.json",
    )
    assert result.windows_total >= 2
    assert len(seen_chunks) == result.windows_total
    flat = [cid for window in seen_chunks for cid in window]
    assert set(flat) == {b["id"] for b in zhongyao_blocks}
    # not a single prefix-only call
    assert len(seen_chunks) > 1


def test_jichu_offline_cursor_emits_v2_candidates(tmp_path: Path) -> None:
    blocks = load_content_blocks(JICHU_BLOCKS)
    result = run_cursor_generation(
        blocks,
        book_template="jichu",
        document_version="jichu.v1.1fcfabb4b4b3",
        generation_batch_id="p5t05-jichu",
        max_chars=120,
        mode="offline",
        out_dir=tmp_path / "jichu",
    )
    assert_full_coverage(blocks, result.covered_chunk_ids)
    assert result.cards
    types = {c.card_type for c in result.cards}
    assert types & {"concept_definition", "mechanism", "relation", "contrast"}
    for card in result.cards:
        model = validate_candidate_card_v2(card)
        assert model.input_hash
        assert model.chunk_ids
