"""P5-T09: versioned publication validate/import/status."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session
from tools.document_pipeline.candidate_schema import compute_content_hash
from tools.document_pipeline.paths import ROOT
from tools.document_pipeline.publish import export_publication, recompute_checksums

from app.catalog.models import (
    Book,
    Card,
    CardSource,
    Chapter,
    Document,
    DocumentChunk,
    DocumentVersion,
)
from app.core.errors import InvalidRequestError, ResourceNotFoundError
from app.db import Base, engine
from app.learning.models import CardReviewState
from app.learning.services import list_due
from app.main import app
from app.models import ReviewState
from app.publishing.models import PublicationImport
from app.publishing.services import (
    get_publication_status,
    import_publication_package,
    validate_publication_package,
)

FIXTURE = ROOT / "tools" / "document_pipeline" / "fixtures" / "validation_p5t06_cards.json"
PREFIX = "pub-import-test-"


def _cards() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cards"]


def _with_hash(card: dict) -> dict:
    out = deepcopy(card)
    out["content_hash"] = compute_content_hash(
        document_version=out["document_version"],
        card_type=out["card_type"],
        question=out["question"],
        answer=out["answer"],
        answer_points=list(out.get("answer_points") or []),
        source_excerpt=out["source_excerpt"],
        chunk_ids=list(out.get("chunk_ids") or []),
    )
    return out


def _approved(card: dict, *, reviewer: str = "alice", suffix: str = "") -> dict:
    out = _with_hash(card)
    if suffix:
        out["id"] = f"{out['id']}{suffix}"
    out["status"] = "approved"
    out["reviewer"] = reviewer
    out["reviewed_at"] = "2026-07-25T04:00:00+00:00"
    out["review_decision"] = "approve"
    out = _with_hash(out)
    return out


def _clean(db: Session) -> None:
    card_ids = list(db.scalars(select(Card.id).where(Card.external_id.like(f"{PREFIX}%"))).all())
    # Also clean cards produced from export fixtures that we tag via external ids.
    exported_ids = [
        "baihu-function-control",
        "single-version-zhongfeng-10",
        "baihu-function-control-conflict",
    ]
    more_ids = list(db.scalars(select(Card.id).where(Card.external_id.in_(exported_ids))).all())
    all_ids = sorted(set(card_ids + more_ids))
    if all_ids:
        db.execute(delete(CardSource).where(CardSource.card_id.in_(all_ids)))
        db.execute(delete(ReviewState).where(ReviewState.card_id.in_(all_ids)))
        db.execute(delete(CardReviewState).where(CardReviewState.card_id.in_(all_ids)))
        db.execute(delete(Card).where(Card.id.in_(all_ids)))
    db.execute(delete(PublicationImport).where(PublicationImport.publication_id.like("pub-test-%")))
    db.execute(delete(DocumentChunk).where(DocumentChunk.pipeline_version.like("p5%")))
    db.execute(delete(Chapter).where(Chapter.recognition_method == "publication_import"))
    db.execute(
        delete(DocumentVersion).where(
            DocumentVersion.source_file_name.in_(["fangji.pdf", "neike.pdf"])
            | DocumentVersion.processing_version.like("p5%")
        )
    )
    db.execute(delete(Document).where(Document.document_key.in_(["fangji", "neike"])))
    db.execute(delete(Book).where(Book.name.in_(["方剂学", "中医内科学"])))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(engine) as session:
        _clean(session)
        yield session
        session.rollback()
        _clean(session)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _build_package(tmp_path: Path, *, publication_id: str = "pub-test-001") -> Path:
    cards = _cards()
    approved = [
        _approved(cards["valid_control"]),
        _approved(cards["single_version_ok"]),
    ]
    # Ensure stable external ids for cleanup/assertions.
    for card in approved:
        assert card["id"]
    pkg = export_publication(
        approved,
        out_dir=tmp_path / publication_id,
        publication_id=publication_id,
    )
    return pkg.out_dir


def _rewrite_hashes(package_dir: Path) -> None:
    files = recompute_checksums(package_dir)
    package_hash = (
        __import__("hashlib")
        .sha256(
            json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        .hexdigest()
    )
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["checksums"] = files
    manifest["package_hash"] = package_hash
    manifest.pop("manifest_hash", None)
    manifest_hash = (
        __import__("hashlib")
        .sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        .hexdigest()
    )
    manifest["manifest_hash"] = manifest_hash
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checksum_payload = {
        "schema_version": 1,
        "publication_id": manifest["publication_id"],
        "files": files,
        "package_hash": package_hash,
        "manifest_hash": manifest_hash,
        "algorithm": "sha256",
    }
    (package_dir / "checksums.json").write_text(
        json.dumps(checksum_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_validate_publication_package_ok(tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path)
    result = validate_publication_package(package_dir)
    assert result.ok is True
    assert result.publication_id == "pub-test-001"
    assert result.counts.cards == 2
    assert result.counts.card_sources >= 2
    assert result.errors == []


@pytest.mark.parametrize("declared", [0, "two", True, -1])
def test_validate_rejects_invalid_or_incorrect_manifest_counts(
    tmp_path: Path, declared: object
) -> None:
    package_dir = _build_package(tmp_path)
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["cards"] = declared
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _rewrite_hashes(package_dir)

    result = validate_publication_package(package_dir)

    assert result.ok is False
    assert any("manifest.counts.cards" in error for error in result.errors)


def test_validate_rejects_manifest_sidecar_hash_disagreement(tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path)
    sidecar_path = package_dir / "checksums.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["package_hash"] = "f" * 64
    sidecar_path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = validate_publication_package(package_dir)

    assert result.ok is False
    assert "manifest and checksums.json package_hash differ" in result.errors


def test_validate_rejects_duplicate_card_identity(tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path)
    cards_path = package_dir / "cards.jsonl"
    lines = [line for line in cards_path.read_text(encoding="utf-8").splitlines() if line]
    cards_path.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["cards"] += 1
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _rewrite_hashes(package_dir)

    result = validate_publication_package(package_dir)

    assert result.ok is False
    assert any("duplicate ids" in error for error in result.errors)


def test_import_creates_catalog_without_due_or_review_state(db: Session, tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path, publication_id="pub-test-import-1")
    due_before = len(list_due(db, limit=1000))
    review_before = int(db.scalar(select(func.count()).select_from(ReviewState)) or 0)
    personal_before = int(db.scalar(select(func.count()).select_from(CardReviewState)) or 0)
    cards_before = int(db.scalar(select(func.count()).select_from(Card)) or 0)

    result = import_publication_package(db, package_dir)
    assert result.status == "imported"
    assert result.idempotent_replay is False
    assert result.stats.cards_created == 2
    assert result.stats.card_sources_created >= 2
    assert result.stats.review_states_created == 0
    assert result.stats.card_review_states_created == 0

    cards = list(
        db.scalars(
            select(Card).where(
                Card.external_id.in_(["baihu-function-control", "single-version-zhongfeng-10"])
            )
        ).all()
    )
    # single_version_ok fixture id may differ; fall back to package cards
    if len(cards) < 2:
        package_card_ids = [
            json.loads(line)["id"]
            for line in (package_dir / "cards.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        cards = list(db.scalars(select(Card).where(Card.external_id.in_(package_card_ids))).all())
    assert len(cards) == 2
    for card in cards:
        assert card.status == "published"
        assert card.content_hash
        sources = list(db.scalars(select(CardSource).where(CardSource.card_id == card.id)).all())
        assert sources
        assert db.scalar(select(ReviewState.id).where(ReviewState.card_id == card.id)) is None
        assert (
            db.scalar(select(CardReviewState.id).where(CardReviewState.card_id == card.id)) is None
        )

    assert int(db.scalar(select(func.count()).select_from(Card)) or 0) == cards_before + 2
    assert len(list_due(db, limit=1000)) == due_before
    assert int(db.scalar(select(func.count()).select_from(ReviewState)) or 0) == review_before
    assert int(db.scalar(select(func.count()).select_from(CardReviewState)) or 0) == personal_before

    status = get_publication_status(db, "pub-test-import-1")
    assert status.status == "imported"
    assert status.stats.cards_created == 2


def test_identical_reimport_is_idempotent(db: Session, tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path, publication_id="pub-test-idempotent")
    first = import_publication_package(db, package_dir)
    cards_after_first = int(db.scalar(select(func.count()).select_from(Card)) or 0)
    sources_after_first = int(db.scalar(select(func.count()).select_from(CardSource)) or 0)
    second = import_publication_package(db, package_dir)
    assert second.idempotent_replay is True
    assert second.status == "imported"
    assert second.stats.cards_created == first.stats.cards_created
    assert int(db.scalar(select(func.count()).select_from(Card)) or 0) == cards_after_first
    assert int(db.scalar(select(func.count()).select_from(CardSource)) or 0) == sources_after_first
    assert (
        db.scalar(
            select(func.count())
            .select_from(PublicationImport)
            .where(PublicationImport.publication_id == "pub-test-idempotent")
        )
        == 1
    )


def test_file_sqlite_concurrent_identical_import_is_idempotent(tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path, publication_id="pub-test-concurrent")
    sqlite_engine = create_engine(
        f"sqlite:///{tmp_path / 'publication-concurrency.db'}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    Base.metadata.create_all(sqlite_engine)
    ready = Barrier(2)
    try:

        def run_import() -> tuple[str, bool]:
            with Session(sqlite_engine) as thread_db:
                ready.wait(timeout=5)
                result = import_publication_package(thread_db, package_dir)
                return result.status, result.idempotent_replay

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: run_import(), range(2)))

        assert sorted(results) == [("imported", False), ("imported", True)]
        with Session(sqlite_engine) as verify_db:
            assert verify_db.scalar(select(func.count()).select_from(PublicationImport)) == 1
            assert verify_db.scalar(select(func.count()).select_from(Card)) == 2
    finally:
        sqlite_engine.dispose()


def test_import_materializes_matching_approved_card_and_missing_sources(
    db: Session, tmp_path: Path
) -> None:
    package_dir = _build_package(tmp_path, publication_id="pub-test-materialize")
    first = import_publication_package(db, package_dir)
    assert first.status == "imported"
    card_id = db.scalar(select(Card.id).where(Card.external_id == "baihu-function-control"))
    assert card_id is not None
    db.execute(delete(CardSource).where(CardSource.card_id == card_id))
    card = db.get(Card, card_id)
    assert card is not None
    card.status = "approved"
    db.execute(
        delete(PublicationImport).where(PublicationImport.publication_id == "pub-test-materialize")
    )
    db.commit()

    result = import_publication_package(db, package_dir)

    db.refresh(card)
    assert result.status == "imported"
    assert result.stats.cards_updated == 1
    assert card.status == "published"
    assert db.scalar(
        select(func.count()).select_from(CardSource).where(CardSource.card_id == card_id)
    )


def test_same_publication_id_different_hash_reports_conflict(db: Session, tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path, publication_id="pub-test-hash-conflict")
    first = import_publication_package(db, package_dir)
    assert first.status == "imported"

    # mutate package content then rehash so validation passes but hashes differ
    alt = tmp_path / "pub-test-hash-conflict-alt"
    shutil.copytree(package_dir, alt)
    cards = [
        json.loads(line)
        for line in (alt / "cards.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cards[0]["answer"] = cards[0]["answer"] + "（修订）"
    cards[0]["content_hash"] = compute_content_hash(
        document_version=cards[0]["document_version"],
        card_type=cards[0]["card_type"],
        question=cards[0]["question"],
        answer=cards[0]["answer"],
        answer_points=list(cards[0].get("answer_points") or []),
        source_excerpt=cards[0]["source_excerpt"],
        chunk_ids=list(cards[0].get("chunk_ids") or []),
    )
    (alt / "cards.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in cards) + "\n",
        encoding="utf-8",
    )
    _rewrite_hashes(alt)

    cards_before = int(db.scalar(select(func.count()).select_from(Card)) or 0)
    result = import_publication_package(db, alt)
    assert result.status == "conflict"
    assert result.idempotent_replay is False
    assert any(c.entity == "publication" for c in result.conflicts)
    assert int(db.scalar(select(func.count()).select_from(Card)) or 0) == cards_before
    # original import record remains
    status = get_publication_status(db, "pub-test-hash-conflict")
    assert status.status == "imported"
    assert status.manifest_hash == first.manifest_hash


def test_card_content_hash_conflict_rolls_back(db: Session, tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path, publication_id="pub-test-card-base")
    base = import_publication_package(db, package_dir)
    assert base.status == "imported"

    # second publication with same card id but different content
    alt_cards_raw = _cards()
    changed = _approved(alt_cards_raw["valid_control"])
    changed["answer"] = changed["answer"] + "（冲突）"
    changed = _with_hash(changed)
    other = _approved(alt_cards_raw["single_version_ok"])
    alt_pkg = export_publication(
        [changed, other],
        out_dir=tmp_path / "pub-test-card-conflict",
        publication_id="pub-test-card-conflict",
    )
    cards_before = int(db.scalar(select(func.count()).select_from(Card)) or 0)
    pubs_before = int(db.scalar(select(func.count()).select_from(PublicationImport)) or 0)
    result = import_publication_package(db, alt_pkg.out_dir)
    assert result.status == "conflict"
    assert any(c.entity == "card" and "content_hash conflict" in c.reason for c in result.conflicts)
    assert int(db.scalar(select(func.count()).select_from(Card)) or 0) == cards_before
    assert int(db.scalar(select(func.count()).select_from(PublicationImport)) or 0) == pubs_before
    # no partial second publication record
    with pytest.raises(ResourceNotFoundError):
        get_publication_status(db, "pub-test-card-conflict")


def test_status_unknown_publication_is_404(db: Session) -> None:
    with pytest.raises(ResourceNotFoundError) as exc:
        get_publication_status(db, "pub-does-not-exist")
    assert exc.value.code == "PUBLICATION_NOT_FOUND"


def test_invalid_package_validate_and_import_fail(tmp_path: Path, db: Session) -> None:
    package_dir = _build_package(tmp_path, publication_id="pub-test-invalid")
    # break checksum deliberately
    cards_path = package_dir / "cards.jsonl"
    cards_path.write_text(cards_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = validate_publication_package(package_dir)
    assert result.ok is False
    assert result.errors
    with pytest.raises(InvalidRequestError) as exc:
        import_publication_package(db, package_dir)
    assert exc.value.code == "PUBLICATION_VALIDATION_FAILED"


def test_admin_publication_api_smoke(client: TestClient, db: Session, tmp_path: Path) -> None:
    package_dir = _build_package(tmp_path, publication_id="pub-test-api")
    headers = {"Authorization": "Bearer test-token", "X-Request-ID": "req_pub_import"}

    validate = client.post(
        "/api/v1/admin/publications/validate",
        headers=headers,
        json={"package_dir": str(package_dir)},
    )
    assert validate.status_code == 200, validate.text
    assert validate.json()["ok"] is True

    imported = client.post(
        "/api/v1/admin/publications/import",
        headers=headers,
        json={"package_dir": str(package_dir)},
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["status"] == "imported"
    assert body["idempotent_replay"] is False

    status = client.get("/api/v1/admin/publications/pub-test-api", headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "imported"

    missing = client.get("/api/v1/admin/publications/missing-pub", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "PUBLICATION_NOT_FOUND"

    # openapi includes the new routes
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/admin/publications/validate" in paths
    assert "/api/v1/admin/publications/import" in paths
    assert "/api/v1/admin/publications/{publication_id}" in paths
