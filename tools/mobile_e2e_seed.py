from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from app import models as _models  # noqa: F401
from app.catalog.models import Book
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
from app.config import get_settings
from app.db import SessionLocal
from app.identity.auth import issue_mobile_activation_code
from app.identity.schemas import OwnerCreate
from app.identity.services import create_owner_with_default_profile
from app.learning.models import CardEnrollment, CardReviewState


def main() -> int:
    settings = get_settings()
    database_url = settings.database_url
    if os.environ.get("WXZY_MOBILE_E2E") != "1":
        raise RuntimeError("WXZY_MOBILE_E2E=1 is required")
    if not database_url.startswith("sqlite") or "tmp" not in database_url:
        raise RuntimeError("mobile E2E seed requires a temporary SQLite database")

    now = datetime.now(UTC)
    with SessionLocal() as db:
        owner = create_owner_with_default_profile(
            db,
            data=OwnerCreate(display_name="Mobile E2E Owner"),
        )
        if owner.learning_profile is None:
            raise RuntimeError("mobile E2E owner profile was not created")
        owner.learning_profile.onboarding_completed_at = now
        owner.learning_profile.subject_priorities = {"中医基础理论": 5}
        owner.learning_profile.initial_self_assessment = {"中医基础理论": 3}
        db.commit()
        book = Book(name="移动端端到端测试", subject="中医基础理论")
        db.add(book)
        db.flush()
        registration = register_document_version(
            db,
            document_values=DocumentCreate(
                document_key="mobile-e2e-document",
                title="移动端端到端测试",
                subject="中医基础理论",
            ),
            version_values=DocumentVersionCreate(
                source_sha256="d" * 64,
                source_file_name="mobile-e2e.pdf",
                page_count=20,
                size_bytes=2048,
                processing_version="mobile-e2e-v1",
            ),
            now=now,
        )
        chapter = create_chapter(
            db,
            ChapterCreate(
                document_version_id=registration.version.id,
                chapter_key="mobile-e2e-yinyang",
                title="阴阳学说",
                level=1,
                sort_order=1,
                pdf_page_index_start=0,
                pdf_page_index_end=19,
                recognition_method="e2e_fixture",
            ),
        )
        chunk = create_document_chunk(
            db,
            DocumentChunkCreate(
                document_version_id=registration.version.id,
                chapter_id=chapter.id,
                chunk_key="mobile-e2e-yinyang-relations",
                chapter_path=["阴阳学说", "基本关系"],
                pdf_page_index_start=11,
                pdf_page_index_end=11,
                printed_page_labels=["12"],
                block_type="paragraph",
                source_text="阴阳双方相互对立、相互依存，并在一定条件下相互转化。",
                cleaned_text="阴阳双方相互对立、相互依存，并在一定条件下相互转化。",
                content_hash="c" * 64,
                quality_status=ChunkQualityStatus.READY,
                quality_flags=[],
                pipeline_version="mobile-e2e-v1",
            ),
        )
        card = create_catalog_card(
            db,
            CatalogCardCreate(
                external_id="mobile-e2e-yinyang-relations",
                book_id=book.id,
                card_type="list",
                question="阴阳的基本关系有哪些？",
                answer="阴阳之间存在对立制约、互根互用、消长平衡与相互转化。",
                answer_points=["对立制约", "互根互用", "消长平衡", "相互转化"],
                content_revision=1,
                content_hash="e" * 64,
                tags=["阴阳"],
                sources=[
                    CardSourceCreate(
                        document_chunk_id=chunk.id,
                        citation_order=0,
                        excerpt="阴阳双方相互对立、相互依存，并在一定条件下相互转化。",
                        pdf_page_index_start=11,
                        pdf_page_index_end=11,
                        printed_page_start_label="12",
                        printed_page_end_label="12",
                    )
                ],
            ),
        )
        db.add_all(
            [
                CardEnrollment(
                    user_id=owner.id,
                    card_id=card.id,
                    status="active",
                    priority=80,
                    source="manual",
                    introduced_at=now - timedelta(days=1),
                ),
                CardReviewState(
                    user_id=owner.id,
                    card_id=card.id,
                    due_at=now - timedelta(minutes=1),
                    stability=1.0,
                    difficulty=5.0,
                    elapsed_days=1.0,
                    scheduled_days=1.0,
                    reps=1,
                    lapses=0,
                    state="review",
                    algorithm_version="fsrs-6.3.1",
                ),
            ]
        )
        db.commit()
        activation_code = issue_mobile_activation_code(db, ttl_seconds=1800)

    print(activation_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
