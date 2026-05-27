from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import HiveUser, UserStatus
from apps.core.models import (
    ChunkEmbedding,
    Comment,
    Post,
    PostStatus,
    PostTag,
    PostWikiDocument,
    Source,
    SourceChunk,
    SourceDocument,
    SourceDocumentFetchStatus,
    SourceDocumentWikiStatus,
    Tag,
    TagType,
    WikiDocument,
    WikiDocumentStatus,
    WikiGenerationType,
    WikiRevision,
    WikiRevisionSource,
)
from apps.core.wiki_embeddings import sync_wiki_document_embedding

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

SEED_DOCUMENTS = [
    {
        "source": {
            "name": "HiveWiki Seed Source",
            "target_url": "https://local.hivewiki.test/wiki-seed",
        },
        "document": {
            "canonical_url": "https://local.hivewiki.test/docs/capstone-wiki-guide",
            "title": "캡스톤 위키 운영 가이드",
            "body_text": (
                "캡스톤 팀이 문서를 수집하고, 검토하고, 위키 문서로 승격하는 "
                "운영 흐름을 정리한 기준 문서입니다."
            ),
        },
        "chunks": [
            {
                "chunk_index": 0,
                "chunk_type": "intro",
                "section_title": "문서 수집 원칙",
                "content_text": (
                    "질문, 회고, 운영 기록 중 반복 활용 가치가 높은 항목을 "
                    "우선적으로 수집해 source chunk로 보관합니다."
                ),
            },
            {
                "chunk_index": 1,
                "chunk_type": "policy",
                "section_title": "위키 승격 기준",
                "content_text": (
                    "두 번 이상 반복된 질문이거나 팀 온보딩에 직접 도움이 되는 "
                    "내용은 위키 문서로 승격합니다."
                ),
            },
            {
                "chunk_index": 2,
                "chunk_type": "workflow",
                "section_title": "운영 루프",
                "content_text": (
                    "수집, 초안 작성, 검토, 게시, 후속 업데이트로 이어지는 "
                    "반복 운영 루프를 정의해 문서 품질을 유지합니다."
                ),
            },
            {
                "chunk_index": 3,
                "chunk_type": "ownership",
                "section_title": "관리 책임",
                "content_text": (
                    "문서 소유자와 리뷰어를 분리해 장기 유지보수 책임을 "
                    "명확히 하고, 갱신 주기를 운영 기준에 포함합니다."
                ),
            },
        ],
        "wiki": {
            "title": "캡스톤 위키 운영 가이드",
            "slug": "capstone-wiki-guide",
            "summary": ("문서 수집, 검토, 승격 절차를 정리한 기본 운영 문서입니다."),
            "content_markdown": """# 캡스톤 위키 운영 가이드

## 문서 수집 원칙
- 반복되는 질문과 답변을 우선 수집합니다.
- 운영 회고와 정책 변경 사항을 source chunk로 저장합니다.
- 논의 당시의 맥락이 사라지지 않도록 결정 배경을 함께 기록합니다.

문서 수집 단계에서는 "나중에 다시 설명해야 하는가"를 가장 중요한 판단 기준으로 삼습니다.
한 번의 답변으로 끝나는 내용보다, 새 팀원이 같은 질문을 반복할 가능성이 있는 주제를 먼저 쌓는 편이
위키의 효율을 높입니다.

## 위키 승격 기준
- 온보딩 효율을 높이는 정보
- 두 번 이상 반복된 질문
- 팀의 공식 기준으로 삼을 수 있는 내용

질문의 빈도만으로 승격 여부를 결정하지는 않습니다.
답변이 어느 정도 안정되어 있는지, 팀의 현재 합의와 충돌하지 않는지,
그리고 이후 운영 과정에서 참조 포인트로 쓰일 수 있는지를 함께 봐야 합니다.

## 운영 루프
1. 커뮤니티나 회고에서 후보 내용을 모읍니다.
2. source chunk 단위로 쪼개고 제목과 맥락을 정리합니다.
3. 위키 초안을 만든 뒤 출처와 연결합니다.
4. 검토가 끝나면 published 상태로 공개합니다.
5. 후속 피드백을 받아 revision을 갱신합니다.

운영 루프는 한 번 쓰고 끝나는 문서보다, 자주 갱신되는 문서에서 특히 중요합니다.
실제 사용자가 보고 있는 문서가 최신 판단 기준을 반영하는지 주기적으로 확인해야 합니다.

## 관리 책임
각 문서에는 최소한 한 명의 관리 책임자가 있어야 합니다.
책임자는 문서가 낡았는지 점검하고, 필요할 경우 revision을 추가하며,
관련 커뮤니티 스레드나 운영 공지를 다시 연결하는 역할을 맡습니다.

리뷰어는 표현을 다듬는 사람이라기보다, 문서가 현재 운영 기준과 맞는지를 확인하는 사람에 가깝습니다.
이 구분이 없으면 위키는 초안은 많고 신뢰할 수 있는 문서는 적은 상태가 되기 쉽습니다.
""",
        },
    },
    {
        "source": {
            "name": "HiveWiki Seed Source",
            "target_url": "https://local.hivewiki.test/wiki-seed",
        },
        "document": {
            "canonical_url": "https://local.hivewiki.test/docs/community-to-wiki",
            "title": "커뮤니티 질문을 위키로 전환하는 기준",
            "body_text": (
                "커뮤니티에서 나온 질문과 답변을 어떤 기준으로 구조화해 "
                "위키 문서로 만드는지 정리한 문서입니다."
            ),
        },
        "chunks": [
            {
                "chunk_index": 0,
                "chunk_type": "criteria",
                "section_title": "선정 기준",
                "content_text": (
                    "질문 빈도, 답변의 안정성, 장기 보존 가치가 높은 항목부터 "
                    "위키 후보로 분류합니다."
                ),
            },
            {
                "chunk_index": 1,
                "chunk_type": "workflow",
                "section_title": "편집 흐름",
                "content_text": (
                    "초안 생성 후 출처 chunk를 연결하고, 요약과 제목을 다듬은 뒤 "
                    "current revision으로 반영합니다."
                ),
            },
            {
                "chunk_index": 2,
                "chunk_type": "quality",
                "section_title": "품질 점검",
                "content_text": (
                    "질문을 문서로 옮길 때는 단일 답변을 복붙하지 말고, "
                    "의견 차이와 확정된 기준을 구분해서 편집합니다."
                ),
            },
            {
                "chunk_index": 3,
                "chunk_type": "maintenance",
                "section_title": "후속 관리",
                "content_text": (
                    "게시 후에도 관련 질문이 다시 나오면 revision을 갱신하고, "
                    "오래된 절차는 archived 후보로 분리합니다."
                ),
            },
        ],
        "wiki": {
            "title": "커뮤니티 질문을 위키로 전환하는 기준",
            "slug": "community-to-wiki-criteria",
            "summary": ("질문, 답변, 회고를 위키 문서로 구조화하는 판단 기준입니다."),
            "content_markdown": """# 커뮤니티 질문을 위키로 전환하는 기준

## 선정 기준
- 반복 빈도가 높은 질문
- 답변의 일관성이 확보된 주제
- 나중에도 참조될 운영 지식

커뮤니티에 올라오는 모든 질문을 곧바로 위키로 옮기면 위키는 금방 잡음이 많아집니다.
질문의 반복 빈도, 답변의 안정성, 이후 온보딩과 운영에 다시 쓰일 가능성을 함께 고려해야
읽을 가치가 있는 문서가 남습니다.

특히 답변이 사람마다 다른 상태라면, 그 질문은 아직 위키 문서보다 토론 스레드에 가까울 수 있습니다.
이때는 문서를 만들기보다 "현재 확인된 사실"과 "열린 이슈"를 분리한 임시 초안이 더 적합합니다.

## 편집 흐름
1. 관련 chunk를 모읍니다.
2. 초안 문서를 작성합니다.
3. revision source를 연결합니다.
4. current revision을 갱신합니다.

편집자는 질문 자체를 그대로 옮기기보다, 나중에 다시 찾을 사람이 어떤 제목으로 검색할지를 먼저 생각해야 합니다.
문서 제목은 질문 문장을 그대로 쓰는 것보다, 해결하려는 주제나 판단 기준을 드러내는 쪽이 검색과 유지보수에 유리합니다.

## 품질 점검
문서를 게시하기 전에는 최소한 세 가지를 확인합니다.

1. 문서의 결론이 현재 운영 기준과 충돌하지 않는가
2. 출처로 연결된 chunk가 실제 본문 주장을 뒷받침하는가
3. 제목과 summary만 읽어도 문서의 용도가 명확한가

품질 점검 단계에서 자주 발견되는 문제는 "질문은 분명한데 답변이 너무 길거나, 반대로 결론은 있는데 근거가 약한 경우"입니다.
이럴 때는 문서를 더 길게 쓰기보다, 결론과 근거를 분리해 구조를 다시 잡는 편이 낫습니다.

## 마크다운 예시
다음은 위키 문서에서 자주 쓰는 구성 요소를 한 번에 점검하기 위한 예시입니다.

> 위키는 단순 저장소가 아니라, 팀의 현재 판단 기준을 읽기 좋은 형태로 유지하는 편집 산출물입니다.

인라인 코드 예시로는 `current_revision`, `source_chunk`, `published` 같은 용어가 자주 등장합니다.

### 체크리스트
- [x] 관련 질문 링크를 모았습니다.
- [x] 핵심 근거가 되는 chunk를 연결했습니다.
- [ ] 운영자 리뷰를 반영했습니다.
- [ ] 후속 revision 필요 여부를 확인했습니다.

### 중첩 리스트
1. 초안 작성
   - 질문 배경 정리
   - 결론 우선 서술
   - 근거 chunk 연결
2. 리뷰
   - 현재 정책과 충돌 여부 확인
   - 검색 키워드 관점에서 제목 점검

### 표
| 항목 | 확인 질문 | 실패 시 조치 |
| --- | --- | --- |
| 제목 | 검색 의도가 드러나는가 | 주제 중심으로 다시 작성 |
| 요약 | 3줄 안에 용도가 설명되는가 | 결론 문장을 앞에 배치 |
| 근거 | 출처 chunk와 연결되는가 | revision source 재정리 |

### 코드 블록
```python
def promote_question_to_wiki(question, chunks):
    if question.repeat_count < 2:
        return "keep_in_community"
    if not chunks:
        return "needs_sources"
    return "ready_for_revision"
```

```json
{
  "title": "커뮤니티 질문을 위키로 전환하는 기준",
  "status": "published",
  "source_count": 4
}
```

### 수식
간단한 점수 예시는 $score = \frac{evidence \times clarity}{maintenance + 1}$ 처럼 표현할 수 있습니다.

블록 수식은 다음처럼 둘 수 있습니다.

$$
priority(q) = \sum_{i=1}^{n} w_i \cdot signal_i(q)
$$

또는

\[
confidence = \frac{verified\_sources}{all\_claims}
\]

---

## 후속 관리
위키는 게시 순간보다 게시 이후가 더 중요합니다.
같은 질문이 다시 들어오면 문서 링크가 실제로 문제를 해결했는지 확인하고,
설명이 부족했다면 revision을 추가해 최신 사례와 표현을 반영합니다.

반대로 더 이상 쓰이지 않는 절차나 이미 폐기된 정책은 archived 후보로 분리해
검색 결과에서 현재 문서와 섞이지 않도록 관리해야 합니다.
""",
        },
    },
    {
        "source": {
            "name": "HiveWiki Seed Source",
            "target_url": "https://local.hivewiki.test/wiki-seed",
        },
        "document": {
            "canonical_url": "https://local.hivewiki.test/docs/footnote-reference-demo",
            "title": "Footnote 참고 문헌 렌더링 예시",
            "body_text": (
                "동일한 참고 문헌을 본문에서 여러 번 인용하는 footnote 스타일이 "
                "어떻게 렌더링되는지 확인하기 위한 데모 문서입니다."
            ),
        },
        "chunks": [
            {
                "chunk_index": 0,
                "chunk_type": "overview",
                "section_title": "주요 내용",
                "content_text": (
                    "2026 Station C 2차 아이데이션 캠프는 AI 기반 콘텐츠 비즈니스와 "
                    "로컬 문제 해결 창업 아이디어 발굴을 중심으로 운영됩니다."
                ),
            },
            {
                "chunk_index": 1,
                "chunk_type": "audience",
                "section_title": "참여 대상",
                "content_text": (
                    "인문대학, 사회과학대학, 경영대학, 글로벌융합대학, 미디어스쿨, "
                    "반도체디스플레이스쿨, 미래융합스쿨 소속 학생이 참여 대상입니다."
                ),
            },
        ],
        "wiki": {
            "title": "Footnote 참고 문헌 렌더링 예시",
            "slug": "footnote-reference-demo",
            "summary": "동일한 footnote 참고 문헌을 여러 번 인용하는 위키 렌더링 예시입니다.",
            "content_markdown": """# 주요 내용

2026 Station C 2차 아이데이션 캠프의 주요 내용은 AI 기반 콘텐츠 비즈니스를 활용한 로컬 문제 해결 창업 아이디어 발굴을 중심으로 구성되어 있다[^1]. 또한 생성형 AI를 활용한 상세페이지 제작 등의 프로그램이 포함되어 있다[^1].

해당 캠프는 인문대학, 사회과학대학, 경영대학, 글로벌융합대학, 미디어스쿨, 반도체디스플레이스쿨, 미래융합스쿨 소속 학생들을 참여 대상으로 하며[^1], 프로그램 참여 시 공결 처리가 진행된다[^1].

# 참고 문헌

[^1]: [2026 Station C 2차 아이데이션 캠프 참여 안내](https://example.com/station-c-camp)
""",
        },
    },
]

SEED_COMMUNITY_POSTS = [
    {
        "author": {
            "username": "ops_lead",
            "email": "ops.lead@local.hivewiki.test",
        },
        "lookup_key": "검색 첫 화면에서 위키와 커뮤니티 비중을 어떻게 가져가면 좋을지 의견 받고 싶습니다.",
        "content_markdown": (
            "검색 첫 화면에서 위키와 커뮤니티 비중을 어떻게 가져가면 좋을지 의견 받고 싶습니다.\n\n"
            "지금은 최신 문서와 최신 질문이 같이 보여야 한다는 쪽과, "
            "위키를 먼저 보여주고 커뮤니티는 보조로 두자는 쪽이 갈리고 있습니다.\n\n"
            "처음 들어오는 사용자 기준으로 어떤 정보가 먼저 보여야 하는지 사례가 있으면 같이 남겨 주세요."
        ),
        "status": PostStatus.PUBLISHED,
        "tags": ["검색", "UX", "온보딩"],
        "wiki_slugs": ["capstone-wiki-guide"],
        "comments": [
            {
                "author": {
                    "username": "product_jane",
                    "email": "product.jane@local.hivewiki.test",
                },
                "content": (
                    "온보딩 사용자는 위키를 먼저 보게 하고, 최근 질문은 두세 개만 아래에 붙이는 쪽이 더 안정적일 것 같습니다."
                ),
            },
            {
                "author": {
                    "username": "design_minu",
                    "email": "design.minu@local.hivewiki.test",
                },
                "content": (
                    "질문 흐름이 살아 있어야 서비스가 비어 보이지 않습니다. 대신 카드 밀도는 지금보다 낮추는 쪽이 좋겠습니다."
                ),
            },
        ],
    },
    {
        "author": {
            "username": "product_jane",
            "email": "product.jane@local.hivewiki.test",
        },
        "lookup_key": "반복되는 운영 질문을 바로 위키로 넘기기 전에",
        "content_markdown": (
            "반복되는 운영 질문을 바로 위키로 넘기기 전에, 커뮤니티에서 어느 정도 합의가 쌓였는지 판단하는 기준이 필요해 보입니다.\n\n"
            "- 답변이 한 사람 의견에만 의존하지 않는지\n"
            "- 다음 분기에도 유효한 내용인지\n"
            "- 링크 하나로 재사용 가능한지\n\n"
            "팀에서 실제로 보는 체크포인트가 있으면 적어 주세요."
        ),
        "status": PostStatus.PUBLISHED,
        "tags": ["운영", "문서화"],
        "wiki_slugs": ["community-to-wiki-criteria"],
        "comments": [
            {
                "author": {
                    "username": "ops_lead",
                    "email": "ops.lead@local.hivewiki.test",
                },
                "content": (
                    "저는 최소 두 번 이상 반복된 질문인지부터 봅니다. 그다음에 답변이 바뀔 가능성이 큰지 확인합니다."
                ),
            }
        ],
    },
    {
        "author": {
            "username": "design_minu",
            "email": "design.minu@local.hivewiki.test",
        },
        "lookup_key": "커뮤니티 피드를 제목 없이 운영하는 방향이 더 맞아 보입니다.",
        "content_markdown": (
            "커뮤니티 피드를 제목 없이 운영하는 방향이 더 맞아 보입니다.\n\n"
            "짧은 맥락을 바로 읽을 수 있어야 흐름이 끊기지 않고, "
            "태그와 작성자만으로도 대부분의 분류는 가능하다고 생각합니다.\n\n"
            "다만 본문 첫 2~3줄만 보이게 할지, 조금 더 길게 보여줄지는 한 번 비교가 필요합니다."
        ),
        "status": PostStatus.PUBLISHED,
        "tags": ["커뮤니티", "피드", "UI"],
        "wiki_slugs": [],
        "comments": [
            {
                "author": {
                    "username": "product_jane",
                    "email": "product.jane@local.hivewiki.test",
                },
                "content": "모바일에서는 3줄 정도, 데스크톱에서는 4~5줄 정도가 적당해 보입니다.",
            }
        ],
    },
    {
        "author": {
            "username": "campus_ari",
            "email": "campus.ari@local.hivewiki.test",
        },
        "lookup_key": "다음 주 온보딩 세션 전에 꼭 문서화해야 할 질문을 모아두는 임시 글입니다.",
        "content_markdown": (
            "다음 주 온보딩 세션 전에 꼭 문서화해야 할 질문을 모아두는 임시 글입니다.\n\n"
            "아직 정리 전이라 draft로 두고, 코멘트로 필요한 주제만 빠르게 붙여 주세요."
        ),
        "status": PostStatus.DRAFT,
        "tags": ["온보딩", "임시정리"],
        "wiki_slugs": [],
        "comments": [],
    },
]


class Command(BaseCommand):
    help = "Seed local wiki data into the current database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-mock-embeddings",
            action="store_true",
            help="Seed deterministic mock embeddings for local testing.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        use_mock_embeddings = options["with_mock_embeddings"]
        seeded_documents = 0
        seeded_revisions = 0
        seeded_sources = 0
        seeded_embeddings = 0
        seeded_posts = 0
        seeded_comments = 0
        seeded_tags = 0
        seeded_users = 0

        for seed in SEED_DOCUMENTS:
            source, _ = Source.objects.update_or_create(
                target_url=seed["source"]["target_url"],
                defaults={
                    "name": seed["source"]["name"],
                    "enabled": True,
                    "updated_at": timezone.now(),
                },
            )

            source_document, _ = SourceDocument.objects.update_or_create(
                source=source,
                canonical_url=seed["document"]["canonical_url"],
                defaults={
                    "title": seed["document"]["title"],
                    "body_text": seed["document"]["body_text"],
                    "fetch_status": SourceDocumentFetchStatus.FETCHED,
                    "wiki_status": SourceDocumentWikiStatus.COMPLETED,
                },
            )

            chunk_instances = []
            for chunk_seed in seed["chunks"]:
                chunk, _ = SourceChunk.objects.update_or_create(
                    source_document=source_document,
                    chunk_index=chunk_seed["chunk_index"],
                    defaults={
                        "chunk_type": chunk_seed["chunk_type"],
                        "section_title": chunk_seed["section_title"],
                        "content_text": chunk_seed["content_text"],
                        "token_count": len(chunk_seed["content_text"].split()),
                        "char_start": 0,
                        "char_end": len(chunk_seed["content_text"]),
                    },
                )
                chunk_instances.append(chunk)

                if use_mock_embeddings:
                    ChunkEmbedding.objects.update_or_create(
                        source_chunk=chunk,
                        embedding_model=EMBEDDING_MODEL,
                        defaults={
                            "embedding_dim": EMBEDDING_DIM,
                            "embedding": self._build_embedding(chunk.chunk_index),
                            "content_hash": self._content_hash(chunk.content_text),
                        },
                    )
                    seeded_embeddings += 1

            wiki_document, created = WikiDocument.objects.update_or_create(
                slug=seed["wiki"]["slug"],
                defaults={
                    "title": seed["wiki"]["title"],
                    "summary": seed["wiki"]["summary"],
                    "status": WikiDocumentStatus.PUBLISHED,
                    "updated_at": timezone.now(),
                },
            )
            seeded_documents += 1
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f"Created wiki document {wiki_document.slug}")
                )

            revision, _ = WikiRevision.objects.update_or_create(
                wiki_document=wiki_document,
                revision_number=1,
                defaults={
                    "content_markdown": seed["wiki"]["content_markdown"],
                    "generation_type": WikiGenerationType.AI,
                    "generation_model": "gpt-5.5",
                },
            )
            seeded_revisions += 1

            wiki_document.current_revision = revision
            wiki_document.save(update_fields=["current_revision", "updated_at"])

            existing_source_links = set(
                WikiRevisionSource.objects.filter(wiki_revision=revision).values_list(
                    "source_chunk_id", flat=True
                )
            )
            for chunk in chunk_instances:
                if chunk.id in existing_source_links:
                    continue
                WikiRevisionSource.objects.create(
                    wiki_revision=revision,
                    source_chunk=chunk,
                    evidence_text=chunk.content_text[:240],
                )
                seeded_sources += 1
            sync_wiki_document_embedding(wiki_document)

        for seed in SEED_COMMUNITY_POSTS:
            author, author_created = self._get_or_create_seed_user(seed["author"])
            if author_created:
                seeded_users += 1

            post = Post.objects.filter(
                author_user=author,
                content_markdown__contains=seed["lookup_key"],
            ).first()
            if post is None:
                post = Post.objects.create(
                    author_user=author,
                    content_markdown=seed["content_markdown"],
                    status=seed["status"],
                )
            else:
                post.content_markdown = seed["content_markdown"]
                post.status = seed["status"]
                post.updated_at = timezone.now()
                post.save(update_fields=["content_markdown", "status", "updated_at"])
            seeded_posts += 1

            tag_ids = []
            for tag_name in seed["tags"]:
                tag, tag_created = self._get_or_create_seed_tag(tag_name)
                if tag_created:
                    seeded_tags += 1
                tag_ids.append(tag.id)
                PostTag.objects.get_or_create(post=post, tag=tag)

            PostTag.objects.filter(post=post).exclude(tag_id__in=tag_ids).delete()

            wiki_document_ids = list(
                WikiDocument.objects.filter(
                    slug__in=seed["wiki_slugs"],
                    status=WikiDocumentStatus.PUBLISHED,
                    current_revision__isnull=False,
                ).values_list("id", flat=True)
            )
            PostWikiDocument.objects.filter(post=post).exclude(
                wiki_document_id__in=wiki_document_ids
            ).delete()
            for wiki_document_id in wiki_document_ids:
                PostWikiDocument.objects.get_or_create(
                    post=post, wiki_document_id=wiki_document_id
                )

            for comment_seed in seed["comments"]:
                comment_author, comment_author_created = self._get_or_create_seed_user(
                    comment_seed["author"]
                )
                if comment_author_created:
                    seeded_users += 1

                Comment.objects.update_or_create(
                    post=post,
                    author_user=comment_author,
                    content=comment_seed["content"],
                    defaults={
                        "updated_at": timezone.now(),
                    },
                )
                seeded_comments += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Seed complete: "
                f"{seeded_documents} wiki documents, "
                f"{seeded_revisions} revisions, "
                f"{seeded_sources} revision sources, "
                f"{seeded_embeddings} embeddings, "
                f"{seeded_users} users, "
                f"{seeded_tags} tags, "
                f"{seeded_posts} posts, "
                f"{seeded_comments} comments."
            )
        )
        if not use_mock_embeddings:
            self.stdout.write(
                self.style.WARNING(
                    "Mock embeddings were skipped. Re-run with "
                    "--with-mock-embeddings if you need deterministic local vectors."
                )
            )

    def _build_embedding(self, seed_value):
        base = seed_value + 1
        return [round(base / 1000, 6)] * EMBEDDING_DIM

    def _content_hash(self, content):
        import hashlib

        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _get_or_create_seed_user(self, seed_user):
        user, created = HiveUser.objects.get_or_create(
            email=seed_user["email"],
            defaults={
                "username": seed_user["username"],
                "status": UserStatus.ACTIVE,
            },
        )
        if not created:
            updates = []
            if user.username != seed_user["username"]:
                user.username = seed_user["username"]
                updates.append("username")
            if user.status != UserStatus.ACTIVE:
                user.status = UserStatus.ACTIVE
                updates.append("status")
            if updates:
                updates.append("updated_at")
                user.save(update_fields=updates)
        return user, created

    def _get_or_create_seed_tag(self, tag_name):
        tag, created = Tag.objects.get_or_create(
            slug=tag_name,
            defaults={
                "name": tag_name,
                "tag_type": TagType.USER,
            },
        )
        if not created:
            updates = []
            if tag.name != tag_name:
                tag.name = tag_name
                updates.append("name")
            if tag.tag_type != TagType.USER:
                tag.tag_type = TagType.USER
                updates.append("tag_type")
            if updates:
                tag.save(update_fields=updates)
        return tag, created
