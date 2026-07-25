"""Automated candidate validation and near-duplicate detection (P5-T06).

Card-level gates beyond schema:
  - question/answer length and minimum knowledge point shape
  - source coverage of answer points / dosage-like claims
  - fabricated entities or dosage not present in source
  - multi-version mixing inside one card
  - exact and near-duplicate detection within a batch

Outputs stay candidates; this stage never promotes to review/learn.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.document_pipeline.candidate_schema import (
    CandidateCardV2,
    CandidateGateError,
    RiskLevel,
    validate_candidate_card_v2,
)

STAGE = "candidate_validation"
STAGE_VERSION = "p5t06-v1"

# Length bounds for a single flashcard (characters).
MIN_QUESTION_LEN = 4
MAX_QUESTION_LEN = 120
MIN_ANSWER_LEN = 2
MAX_ANSWER_LEN = 400
MIN_ANSWER_POINTS = 1
MAX_ANSWER_POINTS = 12

# Near-duplicate thresholds.
NEAR_DUP_QUESTION_RATIO = 0.88
NEAR_DUP_ANSWER_RATIO = 0.90

CN_NUM = r"[零〇一二三四五六七八九十百千万两]+|\d+(?:\.\d+)?"
DOSAGE_RE = re.compile(
    rf"(?P<num>{CN_NUM})\s*(?P<unit>两|钱|分|克|g|mg|毫升|ml|枚|片|丸|剂|寸)",
    re.IGNORECASE,
)
CN_ENTITY_RE = re.compile(r"[\u4e00-\u9fff]{2,12}")
VERSION_TOKEN_RE = re.compile(
    r"(十版教材|九版教材|八版教材|七版教材|五版教材|人卫三版教材|人卫二版教材|"
    r"第[一二三四五六七八九十\d]+版|新世纪|规划教材)"
)
WHITESPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[，。、“”‘’：:；;！!？?、,.·\-—（）()【】\[\]《》<>\"'`~@#$%^&*_+=|\\/]+")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clean(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def normalize_for_compare(text: str) -> str:
    """Normalize text for exact/near-duplicate comparison."""
    t = _clean(text).lower()
    t = PUNCT_RE.sub("", t)
    return t


def char_ngrams(text: str, n: int = 2) -> set[str]:
    s = normalize_for_compare(text)
    if not s:
        return set()
    if len(s) <= n:
        return {s}
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def similarity(a: str, b: str) -> float:
    """Blend n-gram Jaccard with normalized char overlap for short Chinese text."""
    na = normalize_for_compare(a)
    nb = normalize_for_compare(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    jac = jaccard(char_ngrams(na), char_ngrams(nb))
    # character multiset overlap (order-insensitive), helpful for short TCM phrases
    from collections import Counter

    ca, cb = Counter(na), Counter(nb)
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    overlap = inter / union if union else 0.0
    # prefix/containment bonus for near-identical short questions
    contain = 0.0
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if shorter and shorter in longer:
        contain = len(shorter) / len(longer)
    return max(jac, overlap, contain)


def extract_dosage_claims(text: str) -> list[str]:
    claims: list[str] = []
    for m in DOSAGE_RE.finditer(text or ""):
        claims.append(f"{m.group('num')}{m.group('unit')}".lower())
    return claims


def extract_entities(text: str) -> set[str]:
    """Lightweight Chinese entity tokens used for fabricated-entity checks."""
    stop = {
        "什么",
        "哪些",
        "如何",
        "怎样",
        "以及",
        "或者",
        "可以",
        "应当",
        "如果",
        "因为",
        "所以",
        "主要",
        "包括",
        "组成",
        "功用",
        "主治",
        "用法",
        "剂量",
        "注意",
        "禁忌",
        "毒性",
        "定位",
        "操作",
        "证型",
        "治法",
        "代表",
        "教材",
        "版本",
        "分类",
        "原则",
        "法规",
        "伦理",
        "问题",
        "答案",
        "下列",
        "以下",
        "上述",
        "所述",
        "有关",
        "关于",
        "进行",
        "分为",
        "属于",
        "具有",
        "相关",
        "作用",
        "功能",
        "功效",
        "适应",
        "症状",
        "病机",
        "病名",
        "药名",
        "方名",
        "穴位",
        "经络",
    }
    out: set[str] = set()
    for m in CN_ENTITY_RE.finditer(text or ""):
        tok = m.group(0)
        if tok in stop:
            continue
        if len(tok) < 2:
            continue
        out.add(tok)
    return out


def version_tokens(text: str) -> set[str]:
    return {m.group(0) for m in VERSION_TOKEN_RE.finditer(text or "")}


def _as_model(card: CandidateCardV2 | dict[str, Any]) -> CandidateCardV2 | None:
    try:
        return card if isinstance(card, CandidateCardV2) else CandidateCardV2.model_validate(card)
    except Exception:  # noqa: BLE001 - schema failures collected separately
        return None


@dataclass
class Issue:
    code: str
    message: str
    severity: str = "error"  # error | warn

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass
class CardValidationResult:
    card_id: str
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    near_duplicate_of: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "ok": self.ok,
            "issues": [i.to_dict() for i in self.issues],
            "near_duplicate_of": list(self.near_duplicate_of),
        }


@dataclass
class BatchValidationResult:
    results: list[CardValidationResult]
    accepted: list[CandidateCardV2]
    rejected: list[CandidateCardV2]
    stage: str = STAGE
    stage_version: str = STAGE_VERSION
    generated_at: str = field(default_factory=now_iso)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def accepted_count(self) -> int:
        return len(self.accepted)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_version": self.stage_version,
            "generated_at": self.generated_at,
            "status": "candidate_only",
            "ok": self.ok,
            "accepted_count": len(self.accepted),
            "rejected_count": len(self.rejected),
            "results": [r.to_dict() for r in self.results],
            "accepted_ids": [c.id for c in self.accepted],
            "rejected_ids": [c.id for c in self.rejected],
        }

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "validation_report.json").write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "accepted.jsonl").write_text(
            "".join(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n" for c in self.accepted),
            encoding="utf-8",
        )
        (out_dir / "rejected.jsonl").write_text(
            "".join(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n" for c in self.rejected),
            encoding="utf-8",
        )


def check_schema_and_gate(card: CandidateCardV2 | dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    try:
        validate_candidate_card_v2(card)
    except CandidateGateError as exc:
        for err in exc.errors:
            issues.append(Issue(code="schema_gate", message=err))
    except Exception as exc:  # noqa: BLE001
        issues.append(Issue(code="schema_gate", message=f"schema: {exc}"))
    return issues


def check_length_and_knowledge_point(card: CandidateCardV2) -> list[Issue]:
    issues: list[Issue] = []
    q = _clean(card.question)
    a = _clean(card.answer)
    if len(q) < MIN_QUESTION_LEN:
        issues.append(Issue("question_too_short", f"question length {len(q)} < {MIN_QUESTION_LEN}"))
    if len(q) > MAX_QUESTION_LEN:
        issues.append(Issue("question_too_long", f"question length {len(q)} > {MAX_QUESTION_LEN}"))
    if len(a) < MIN_ANSWER_LEN:
        issues.append(Issue("answer_too_short", f"answer length {len(a)} < {MIN_ANSWER_LEN}"))
    if len(a) > MAX_ANSWER_LEN:
        issues.append(Issue("answer_too_long", f"answer length {len(a)} > {MAX_ANSWER_LEN}"))

    points = [p for p in (card.answer_points or []) if _clean(p)]
    # minimal knowledge point: either explicit points or a short single-claim answer
    if not points:
        if len(a) > 80 or "；" in a or ";" in a or a.count("。") > 1:
            issues.append(
                Issue(
                    "missing_min_knowledge_point",
                    "long multi-claim answer requires answer_points for one recall target",
                )
            )
    else:
        if len(points) > MAX_ANSWER_POINTS:
            issues.append(
                Issue(
                    "too_many_answer_points",
                    f"answer_points count {len(points)} > {MAX_ANSWER_POINTS}",
                )
            )
    return issues


def check_source_coverage(card: CandidateCardV2) -> list[Issue]:
    issues: list[Issue] = []
    source_blob = " ".join(
        [
            card.source_excerpt or "",
            *[s.excerpt for s in card.sources or []],
        ]
    )
    source_norm = normalize_for_compare(source_blob)
    if not source_norm:
        issues.append(Issue("missing_source", "source_excerpt/sources empty"))
        return issues

    # answer points should be covered by source text (normalized containment)
    for point in card.answer_points or []:
        p = normalize_for_compare(point)
        if not p:
            continue
        if p not in source_norm and similarity(point, source_blob) < 0.55:
            issues.append(
                Issue(
                    "source_coverage_fail",
                    f"answer_point not covered by source: {point[:40]}",
                )
            )

    # short answers should largely appear in source
    ans = normalize_for_compare(card.answer)
    if ans and len(ans) <= 40 and ans not in source_norm and similarity(card.answer, source_blob) < 0.5:
        issues.append(Issue("source_coverage_fail", "answer not covered by source"))

    return issues


def check_fabricated_dosage_or_entity(card: CandidateCardV2) -> list[Issue]:
    issues: list[Issue] = []
    source_blob = " ".join(
        [
            card.source_excerpt or "",
            *[s.excerpt for s in card.sources or []],
        ]
    )
    source_norm = normalize_for_compare(source_blob)
    answer_blob = " ".join([card.answer, *list(card.answer_points or [])])

    # dosage claims in answer must appear in source
    for claim in extract_dosage_claims(answer_blob):
        if normalize_for_compare(claim) not in source_norm:
            # also try without unit spacing variants already normalized
            issues.append(
                Issue(
                    "fabricated_dosage",
                    f"dosage claim not found in source: {claim}",
                )
            )

    # For high/critical cards with dosage-like types, extra strictness already above.
    # Entity fabrication: content tokens in answer that never appear in source.
    # Keep conservative: only flag when multiple novel multi-char entities appear
    # and the card is not a pure definition with short source.
    answer_entities = extract_entities(answer_blob)
    source_entities = extract_entities(source_blob)
    novel = sorted(e for e in answer_entities if e not in source_blob and all(e not in se for se in source_entities))
    # filter novel tokens that are substrings of source continuous text
    novel = [e for e in novel if e not in source_blob]
    if len(novel) >= 2 and card.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL, "high", "critical"}:
        issues.append(
            Issue(
                "fabricated_entity",
                f"answer introduces entities absent from source: {', '.join(novel[:5])}",
            )
        )
    return issues


def check_multi_version_mix(card: CandidateCardV2) -> list[Issue]:
    issues: list[Issue] = []
    blob = " ".join(
        [
            card.question or "",
            card.answer or "",
            " ".join(card.answer_points or []),
            " ".join(card.tags or []),
            card.source_excerpt or "",
        ]
    )
    tokens = version_tokens(blob)
    if len(tokens) >= 2:
        # one card mixing multiple textbook versions is invalid
        issues.append(
            Issue(
                "multi_version_mix",
                f"card mixes multiple versions: {', '.join(sorted(tokens))}",
            )
        )
    # versioned classification cards must keep an explicit version cue
    if card.card_type == "versioned_classification" and not tokens:
        has_flag = "multi_version" in (card.risk_flags or []) or any(
            "版" in t for t in (card.tags or [])
        )
        if not has_flag:
            issues.append(
                Issue(
                    "missing_version_cue",
                    "versioned_classification card lacks explicit version token",
                )
            )
    return issues


def validate_card(card: CandidateCardV2 | dict[str, Any]) -> CardValidationResult:
    """Validate a single candidate. Does not consider batch duplicates."""
    raw_id = ""
    if isinstance(card, CandidateCardV2):
        raw_id = card.id
    elif isinstance(card, dict):
        raw_id = str(card.get("id") or "")

    issues = check_schema_and_gate(card)
    model = _as_model(card)
    if model is None:
        return CardValidationResult(card_id=raw_id or "unknown", ok=False, issues=issues)

    issues.extend(check_length_and_knowledge_point(model))
    issues.extend(check_source_coverage(model))
    issues.extend(check_fabricated_dosage_or_entity(model))
    issues.extend(check_multi_version_mix(model))

    # gate helper also returns list; ensure we don't double-count if schema already ran
    # (schema path already includes gate_candidate_card)
    error_issues = [i for i in issues if i.severity == "error"]
    return CardValidationResult(card_id=model.id, ok=not error_issues, issues=issues)


def find_near_duplicates(
    cards: Sequence[CandidateCardV2],
    *,
    question_threshold: float = NEAR_DUP_QUESTION_RATIO,
    answer_threshold: float = NEAR_DUP_ANSWER_RATIO,
) -> dict[str, list[str]]:
    """Return map of card_id -> list of near-duplicate ids (same document_version)."""
    out: dict[str, list[str]] = {c.id: [] for c in cards}
    n = len(cards)
    for i in range(n):
        a = cards[i]
        for j in range(i + 1, n):
            b = cards[j]
            if a.document_version != b.document_version:
                continue
            # exact content hash
            if a.content_hash and a.content_hash == b.content_hash:
                out[a.id].append(b.id)
                out[b.id].append(a.id)
                continue
            q_sim = similarity(a.question, b.question)
            a_sim = similarity(a.answer, b.answer)
            if q_sim >= question_threshold and a_sim >= answer_threshold:
                out[a.id].append(b.id)
                out[b.id].append(a.id)
            elif q_sim >= 0.97 and a.card_type == b.card_type:
                # near-identical questions of same type even if answer slightly differs
                out[a.id].append(b.id)
                out[b.id].append(a.id)
    # unique preserve order
    for k, vals in out.items():
        out[k] = list(dict.fromkeys(vals))
    return out


def validate_candidate_batch(
    cards: Sequence[CandidateCardV2 | dict[str, Any]],
    *,
    fail_near_duplicates: bool = True,
) -> BatchValidationResult:
    """Validate a batch of candidates with schema, coverage, and near-dup checks."""
    models: list[CandidateCardV2] = []
    results: list[CardValidationResult] = []
    accepted: list[CandidateCardV2] = []
    rejected: list[CandidateCardV2] = []

    # first pass: per-card checks
    for card in cards:
        result = validate_card(card)
        model = _as_model(card)
        if model is not None:
            models.append(model)
        results.append(result)

    # second pass: near-duplicate annotations on models that passed schema enough to parse
    id_to_result: dict[str, CardValidationResult] = {r.card_id: r for r in results}
    near = find_near_duplicates([m for m in models])
    for card_id, dups in near.items():
        if not dups or card_id not in id_to_result:
            continue
        marked = id_to_result[card_id]
        marked.near_duplicate_of = dups
        if fail_near_duplicates:
            marked.issues.append(
                Issue(
                    code="near_duplicate",
                    message=f"near-duplicate of: {', '.join(dups[:5])}",
                )
            )
            marked.ok = False

    # Acceptance criteria: duplicates intercepted — reject all marked near_duplicate.
    seen_ids: set[str] = set()
    for card in models:
        if card.id in seen_ids:
            continue
        seen_ids.add(card.id)
        current = id_to_result.get(card.id)
        if current is not None and current.ok:
            accepted.append(card)
        else:
            rejected.append(card)

    # include unparsable cards as rejected placeholders? they won't be models.
    # Results already capture their issues.
    return BatchValidationResult(results=results, accepted=accepted, rejected=rejected)


def load_candidates(source: Path | str | Sequence[dict[str, Any] | CandidateCardV2]) -> list[Any]:
    if isinstance(source, (list, tuple)):
        return list(source)
    path = source if isinstance(source, Path) else Path(str(source))
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    data = json.loads(raw)
    if isinstance(data, dict) and "cards" in data:
        return list(data["cards"])
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "card" in data:
        return [data["card"]]
    raise ValueError(f"unsupported candidate payload: {path}")


__all__ = [
    "STAGE",
    "STAGE_VERSION",
    "BatchValidationResult",
    "CardValidationResult",
    "Issue",
    "check_fabricated_dosage_or_entity",
    "check_length_and_knowledge_point",
    "check_multi_version_mix",
    "check_schema_and_gate",
    "check_source_coverage",
    "extract_dosage_claims",
    "find_near_duplicates",
    "load_candidates",
    "normalize_for_compare",
    "similarity",
    "validate_candidate_batch",
    "validate_card",
]
