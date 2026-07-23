"""Shared filesystem roots and document keys for the offline pipeline."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Design target layout (data/ is gitignored).
PIPELINE_DATA_ROOT = ROOT / "data" / "document-pipeline"

# Legacy MinerU validation paths kept for sample CLI compatibility.
DEFAULT_MINERU_BASE = "https://mineru.net"
DEFAULT_SAMPLES = ROOT / "data" / "mineru" / "samples"
DEFAULT_RESULTS = ROOT / "data" / "mineru" / "results"
DEFAULT_RUNS = ROOT / "data" / "mineru" / "runs"
DEFAULT_CARDS = ROOT / "data" / "mineru" / "cards"
DEFAULT_CARD_BATCH = ROOT / "data" / "mineru" / "results" / "a67c429e-956c-4f28-bec6-69c3b71e17fa"
SCHEMA_PATH = DEFAULT_CARDS / "candidate_card.schema.json"

# Canonical document keys for the 7-book corpus (DOC-001).
DOCUMENT_KEYS: dict[str, str] = {
    "neike": "学霸笔记—中医内科学(1).pdf",
    "jichu": "学霸笔记—中医基础理论(1).pdf",
    "zhenduan": "学霸笔记—中医诊断学(1).pdf",
    "zhongyao": "学霸笔记—中药学(1).pdf",
    "renwen": "学霸笔记—人文(1).pdf",
    "fangji": "学霸笔记—方剂学(1).pdf",
    "zhenjiu": "学霸笔记—针灸学(1).pdf",
}

# Design-time page counts (re-verified by inventory in P3-T02).
DOCUMENT_PAGE_COUNTS: dict[str, int] = {
    "neike": 149,
    "jichu": 102,
    "zhenduan": 92,
    "zhongyao": 88,
    "renwen": 39,
    "fangji": 140,
    "zhenjiu": 94,
}

CORPUS_PAGE_TOTAL = sum(DOCUMENT_PAGE_COUNTS.values())  # 704
