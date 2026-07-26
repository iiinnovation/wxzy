from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.api.v1.identity import get_wechat_client
from app.catalog.models import (
    Book,
    Card,
    CardSource,
    Chapter,
    Document,
    DocumentChunk,
    DocumentVersion,
)
from app.catalog.read_models import list_learning_books
from app.catalog.schemas import (
    CardSourceCreate,
    CatalogCardCreate,
    ChapterCreate,
    ChunkQualityStatus,
    DocumentChunkCreate,
    DocumentCreate,
    DocumentVersionCreate,
)
from app.catalog.services import (
    create_catalog_card,
    create_chapter,
    create_document_chunk,
    register_document_version,
)
from app.config import AppEnvironment, AuthMode, Settings
from app.db import engine
from app.identity.models import LearningProfile, LearningProfileAudit, User, UserSession
from app.identity.wechat import WeChatCodeError, WeChatIdentity
from app.learning.models import CardEnrollment, CardReviewState
from app.learning.schemas import EnrollmentStatus
from app.learning.services import change_enrollment_status, introduce_enrollment
from app.main import app


def _clean(db: Session) -> None:
    db.execute(delete(CardReviewState))
    db.execute(delete(CardEnrollment))
    db.execute(delete(LearningProfileAudit))
    db.execute(delete(LearningProfile))
    db.execute(delete(UserSession))
    db.execute(delete(User))
    db.execute(delete(CardSource))
    db.execute(delete(Card).where(Card.external_id.like("enroll-api-%")))
    db.execute(delete(DocumentChunk).where(DocumentChunk.chunk_key.like("enroll-api-%")))
    db.execute(delete(Chapter).where(Chapter.chapter_key.like("enroll-api-%")))
    db.execute(delete(DocumentVersion))
    db.execute(delete(Document).where(Document.document_key.like("enroll-api-%")))
    db.execute(delete(Book).where(Book.name.like("Enroll API%")))
    db.commit()


@pytest.fixture
def db() -> Iterator[Session]:
    session = Session(engine)
    _clean(session)
    try:
        yield session
    finally:
        session.close()
        with Session(engine) as cleanup:
            _clean(cleanup)


class FakeWeChatClient:
    def exchange(self, code: str) -> WeChatIdentity:
        if code != "valid-code":
            raise WeChatCodeError()
        return WeChatIdentity(openid="openid-enroll")


@pytest.fixture
def auth_context(db: Session) -> Iterator[tuple[TestClient, Settings]]:
    settings = Settings(
        environment=AppEnvironment.TEST,
        auth_mode=AuthMode.WECHAT,
        wechat_app_id="wx-test-app",
        wechat_app_secret="wechat-test-secret",
        session_ttl_seconds=3600,
    )
    app.dependency_overrides[get_wechat_client] = lambda: FakeWeChatClient()
    from app.config import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, settings
    app.dependency_overrides.pop(get_wechat_client, None)
    app.dependency_overrides.pop(get_settings, None)


def _login(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/auth/wechat", json={"code": "valid-code"})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "req_enroll"}


def _seed_chapter(db: Session) -> tuple[int, list[int]]:
    book = Book(name="Enroll API Book", subject="方剂学")
    db.add(book)
    db.flush()
    registration = register_document_version(
        db,
        document_values=DocumentCreate(
            document_key="enroll-api-doc",
            title="API Book",
            subject="方剂学",
        ),
        version_values=DocumentVersionCreate(
            source_sha256="a" * 64,
            source_file_name="api.pdf",
            page_count=20,
            size_bytes=2048,
            processing_version="pipeline-v2",
        ),
        now=datetime(2026, 7, 22, 2, 0, tzinfo=UTC),
    )
    chapter = create_chapter(
        db,
        ChapterCreate(
            document_version_id=registration.version.id,
            chapter_key="enroll-api-ch-1",
            title="第一章",
            level=1,
            sort_order=1,
            pdf_page_index_start=0,
            pdf_page_index_end=9,
            recognition_method="heading_layout",
        ),
    )
    card_ids: list[int] = []
    for index in range(1, 4):
        chunk = create_document_chunk(
            db,
            DocumentChunkCreate(
                document_version_id=registration.version.id,
                chapter_id=chapter.id,
                chunk_key=f"enroll-api-chunk-{index}",
                chapter_path=["方剂学", "第一章"],
                pdf_page_index_start=index,
                pdf_page_index_end=index,
                printed_page_labels=[str(index + 1)],
                block_type="paragraph",
                source_text=f"source {index}",
                cleaned_text=f"clean {index}",
                content_hash=f"{index:064x}"[-64:],
                quality_status=ChunkQualityStatus.READY,
                quality_flags=[],
                pipeline_version="pipeline-v2",
            ),
        )
        card = create_catalog_card(
            db,
            CatalogCardCreate(
                external_id=f"enroll-api-card-{index}",
                book_id=book.id,
                card_type="definition",
                question=f"问题 {index}",
                answer=f"答案 {index}",
                content_revision=1,
                content_hash=f"{(index + 10):064x}"[-64:],
                answer_points=[f"点 {index}"],
                tags=["api"],
                sources=[
                    CardSourceCreate(
                        document_chunk_id=chunk.id,
                        citation_order=0,
                        excerpt=f"摘录 {index}",
                        pdf_page_index_start=index,
                        pdf_page_index_end=index,
                    )
                ],
            ),
        )
        card_ids.append(card.id)
    return chapter.id, card_ids


def test_post_chapter_enrollment_is_idempotent_and_queued_only(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    token = _login(client)["access_token"]
    chapter_id, card_ids = _seed_chapter(db)

    first = client.post(
        "/api/v1/enrollments",
        headers=_headers(token),
        json={"scope": "chapter", "chapter_id": chapter_id, "priority": 65},
    )
    second = client.post(
        "/api/v1/enrollments",
        headers=_headers(token),
        json={"scope": "chapter", "chapter_id": chapter_id, "priority": 10},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    body = first.json()
    assert body["scope"] == "chapter"
    assert body["created_count"] == 3
    assert body["existing_count"] == 0
    assert body["card_ids"] == card_ids
    assert all(item["status"] == "queued" for item in body["enrollments"])
    assert all(item["source"] == "chapter" for item in body["enrollments"])
    assert second.json()["created_count"] == 0
    assert second.json()["existing_count"] == 3
    assert db.scalar(select(CardReviewState.id).limit(1)) is None


def test_patch_suspend_enrollment(db: Session, auth_context: tuple[TestClient, Settings]) -> None:
    client, _settings = auth_context
    token = _login(client)["access_token"]
    chapter_id, _card_ids = _seed_chapter(db)
    created = client.post(
        "/api/v1/enrollments",
        headers=_headers(token),
        json={"scope": "chapter", "chapter_id": chapter_id},
    ).json()
    enrollment_id = created["enrollments"][0]["id"]

    # queued cannot suspend; introduce via service then suspend via API
    introduce_enrollment(
        db, enrollment_id=enrollment_id, now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC)
    )

    response = client.patch(
        f"/api/v1/enrollments/{enrollment_id}",
        headers=_headers(token),
        json={"status": "suspended"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "suspended"
    assert db.get(CardReviewState, db.scalar(select(CardReviewState.id))) is not None


def test_patch_chapter_pause_resume_is_idempotent_and_preserves_queued(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    token = _login(client)["access_token"]
    chapter_id, _card_ids = _seed_chapter(db)
    created = client.post(
        "/api/v1/enrollments",
        headers=_headers(token),
        json={"scope": "chapter", "chapter_id": chapter_id},
    ).json()

    for item in created["enrollments"][:2]:
        introduce_enrollment(
            db,
            enrollment_id=item["id"],
            now=datetime(2026, 7, 22, 9, 0, tzinfo=UTC),
        )

    url = f"/api/v1/chapters/{chapter_id}/enrollments"
    paused = client.patch(url, headers=_headers(token), json={"status": "suspended"})
    replay = client.patch(url, headers=_headers(token), json={"status": "suspended"})
    resumed = client.patch(url, headers=_headers(token), json={"status": "active"})

    assert paused.status_code == 200, paused.text
    assert paused.json()["updated_count"] == 2
    assert paused.json()["unchanged_count"] == 0
    assert paused.json()["ignored_count"] == 1
    assert replay.json()["updated_count"] == 0
    assert replay.json()["unchanged_count"] == 2
    assert replay.json()["ignored_count"] == 1
    assert resumed.json()["updated_count"] == 2
    assert (
        db.scalar(
            select(CardEnrollment.status).where(
                CardEnrollment.id == created["enrollments"][2]["id"]
            )
        )
        == "queued"
    )
    assert len(list(db.scalars(select(CardReviewState)))) == 2


def test_catalog_counts_are_owner_scoped_and_include_enrollment_states(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    login = _login(client)
    token = login["access_token"]
    chapter_id, card_ids = _seed_chapter(db)
    db.execute(update(Card).where(Card.id.in_(card_ids)).values(status="published"))
    db.commit()
    created = client.post(
        "/api/v1/enrollments",
        headers=_headers(token),
        json={"scope": "chapter", "chapter_id": chapter_id},
    ).json()

    first = created["enrollments"][0]["id"]
    second = created["enrollments"][1]["id"]
    introduce_enrollment(db, enrollment_id=first)
    introduce_enrollment(db, enrollment_id=second)
    change_enrollment_status(
        db,
        enrollment_id=second,
        target_status=EnrollmentStatus.SUSPENDED,
    )

    books = client.get("/api/v1/catalog/books", headers=_headers(token))
    chapters = client.get(
        f"/api/v1/catalog/books/{db.get(Card, card_ids[0]).book_id}/chapters",
        headers=_headers(token),
    )

    assert books.status_code == 200, books.text
    assert chapters.status_code == 200, chapters.text
    counts = chapters.json()[0]
    assert counts["published_card_count"] == 3
    assert counts["enrolled_card_count"] == 3
    assert counts["queued_card_count"] == 1
    assert counts["active_card_count"] == 1
    assert counts["suspended_card_count"] == 1
    foreign = list_learning_books(db, user_id=login["owner"]["id"] + 10_000)
    assert foreign[0].enrolled_card_count == 0
    assert foreign[0].active_card_count == 0


def test_catalog_includes_parent_chapter_with_subtree_counts(
    db: Session, auth_context: tuple[TestClient, Settings]
) -> None:
    client, _settings = auth_context
    token = _login(client)["access_token"]
    child_id, card_ids = _seed_chapter(db)
    child = db.get(Chapter, child_id)
    assert child is not None
    parent = create_chapter(
        db,
        ChapterCreate(
            document_version_id=child.document_version_id,
            chapter_key="enroll-api-parent",
            title="总论",
            level=1,
            sort_order=0,
            pdf_page_index_start=0,
            pdf_page_index_end=19,
            recognition_method="heading_layout",
        ),
    )
    child.parent_id = parent.id
    child.level = 2
    db.execute(update(Card).where(Card.id.in_(card_ids)).values(status="published"))
    db.commit()

    book_id = db.get(Card, card_ids[0]).book_id
    response = client.get(
        f"/api/v1/catalog/books/{book_id}/chapters",
        headers=_headers(token),
    )
    parent_cards = client.get(
        f"/api/v1/catalog/cards?book_id={book_id}&chapter_id={parent.id}",
        headers=_headers(token),
    )
    books = client.get("/api/v1/catalog/books", headers=_headers(token))

    assert response.status_code == 200, response.text
    by_id = {row["id"]: row for row in response.json()}
    assert set(by_id) == {parent.id, child.id}
    assert by_id[parent.id]["parent_id"] is None
    assert by_id[parent.id]["published_card_count"] == 3
    assert by_id[child.id]["parent_id"] == parent.id
    assert by_id[child.id]["published_card_count"] == 3
    assert parent_cards.status_code == 200, parent_cards.text
    assert parent_cards.json()["total"] == 3
    assert books.status_code == 200, books.text
    assert books.json()[0]["chapter_count"] == 2
