# 합격자소서 첨삭 시스템 — 수집·전처리·임베딩 설계서

> 작성일: 2026-05-21  
> 작성자: 전처리·임베딩 담당  
> 목적: 팀원과의 역할 분담을 위한 DB 설계 요청 + 전처리·임베딩 파이프라인 확정

---

## 1. 수집 기업 및 예상 건수

| 기업 | 업종 | 잡코리아 | 링커리어 | 합계 |
|------|------|---------|---------|------|
| 삼성전자 | 전자/반도체 | 248 | 946 | **1,194** |
| SK하이닉스 | 반도체 | 89 | 247 | **336** |
| LG전자 | 전자 | 87 | 387 | **474** |
| 포스코 | 철강 | 87 | 237 | **324** |
| 한국전력 | 에너지/공기업 | 88 | 121 | **209** |
| 현대자동차 | 자동차 | 127 | 361 | **488** |
| 기아 | 자동차 | 36 | 151 | **187** |
| 농협은행 | 은행 | 56 | 71 | **127** |
| 기업은행 | 은행 | 37 | 100 | **137** |
| 신한은행 | 은행 | 32 | 66 | **98** |
| 우리은행 | 은행 | 29 | 69 | **98** |
| 국민은행 | 은행 | 29 | 52 | **81** |
| 하나은행 | 은행 | 19 | 446 | **465** |
| **합계** | | **964** | **3,254** | **4,218** |

> - 잡코리아 1건 = Q&A 평균 3~4쌍 → 약 2,900~3,900 Q&A 쌍  
> - 링커리어 1건 = 자소서 전체(단일 텍스트) → 전처리로 Q&A 분리 필요  
> - 예상 임베딩 대상: **12,000~15,000 Q&A 단위**

---

## 2. 플랫폼별 데이터 비교

| 항목 | 잡코리아 | 링커리어 |
|------|---------|---------|
| 수집 방식 | HTML 파싱 (requests + BS4) | GraphQL API |
| 로그인 필요 | 없음 | 없음 |
| Q&A 구조 | 이미 분리됨 (dt/dd) | 단일 content 문자열 |
| 스펙 정보 | 학교·학점·어학·자격증 (ul.specLists) | university, major, role만 |
| 지원 시기 | year, season (상/하반기) | types (신입/경력) |
| 홍보 문구 | 없음 | 도입부에 포함될 수 있음 |

---

## 3. DB 스키마 설계 (팀원 구현 요청)

### 3-1. 핵심 원칙

1. **두 플랫폼을 단일 테이블에 통합** — `source` 컬럼으로 구분
2. **원본 스펙 보존** — `spec_raw` TEXT 로 그대로 저장 (플랫폼마다 형식 다름)
3. **공통 추출 필드** — university, major를 별도 컬럼으로 정규화
4. **Q&A는 별도 테이블** — 임베딩 단위가 Q&A 쌍이므로 `qna` 테이블에 저장
5. **임베딩은 별도 테이블** — `qna_embeddings` 로 분리 (벡터 DB와 동기화용)

### 3-2. 테이블 정의 (SQLite)

```sql
-- ── essays: 자소서 1건 = 1행 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS essays (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 플랫폼 식별
    source          TEXT NOT NULL CHECK(source IN ('jobkorea','linkareer')),
    source_id       TEXT UNIQUE NOT NULL,   -- jobkorea: view_id, linkareer: graphql id

    -- 기업 정보
    company         TEXT NOT NULL,          -- 정제된 기업명 (예: "삼성전자")
    search_term     TEXT,                   -- 수집 시 사용한 검색어
    org_type        TEXT,                   -- 'corp' | 'bank' | 'public' (업종 대분류)

    -- 채용 정보
    role            TEXT,                   -- 직무·직렬 (예: "소프트웨어개발자")
    hire_type       TEXT,                   -- '신입' | '경력' | '인턴'
    year            TEXT,                   -- 지원 연도 (예: "2023")
    season          TEXT,                   -- '상반기' | '하반기' | '수시' | '인턴'

    -- 지원자 스펙 (공통 추출)
    university      TEXT,                   -- 출신 학교
    major           TEXT,                   -- 전공
    spec_raw        TEXT,                   -- 원본 스펙 전체 (플랫폼별 원문 그대로)

    -- 메타
    url             TEXT,
    crawled_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_essays_company    ON essays(company);
CREATE INDEX IF NOT EXISTS idx_essays_source     ON essays(source);
CREATE INDEX IF NOT EXISTS idx_essays_org_type   ON essays(org_type);
CREATE INDEX IF NOT EXISTS idx_essays_role       ON essays(role);


-- ── qna: Q&A 쌍 1개 = 1행 (임베딩 단위) ─────────────────────────────
CREATE TABLE IF NOT EXISTS qna (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    essay_id        INTEGER NOT NULL REFERENCES essays(id) ON DELETE CASCADE,

    q_num           TEXT,                   -- "Q1", "1." 등 원본 번호
    question        TEXT,                   -- 질문 원문
    answer          TEXT NOT NULL,          -- 답변 원문

    -- 전처리 결과 (전처리 담당이 채움)
    question_clean  TEXT,                   -- 정제된 질문
    answer_clean    TEXT,                   -- 정제된 답변
    question_type   TEXT,                   -- 'growth' | 'motivation' | 'fit' |
                                            -- 'experience' | 'personality' | 'goal'
    char_count      INTEGER,                -- 답변 글자수 (원본)
    is_valid        INTEGER DEFAULT 1       -- 0: 필터링된 항목 (너무 짧거나 오매칭)
);

CREATE INDEX IF NOT EXISTS idx_qna_essay_id      ON qna(essay_id);
CREATE INDEX IF NOT EXISTS idx_qna_question_type ON qna(question_type);
CREATE INDEX IF NOT EXISTS idx_qna_company       ON qna(essay_id);  -- essays join 용


-- ── qna_embeddings: 벡터 임베딩 동기화 테이블 ────────────────────────
-- (ChromaDB의 persistent ID를 SQLite에도 기록해 매핑 유지)
CREATE TABLE IF NOT EXISTS qna_embeddings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    qna_id          INTEGER UNIQUE NOT NULL REFERENCES qna(id) ON DELETE CASCADE,
    chroma_id       TEXT UNIQUE,            -- ChromaDB에 저장된 document ID
    model_name      TEXT,                   -- 임베딩 모델 (예: "BAAI/bge-m3")
    embedded_at     TEXT
);
```

### 3-3. `org_type` 값 기준

| org_type | 해당 기업 |
|----------|----------|
| `corp` | 삼성전자, SK하이닉스, LG전자, 포스코, 현대자동차, 기아 |
| `public` | 한국전력 |
| `bank` | 농협은행, 기업은행, 신한은행, 우리은행, 국민은행, 하나은행 |

### 3-4. 팀원 구현 요청 사항

- `essays.source_id`: 잡코리아는 `str(view_id)`, 링커리어는 GraphQL 반환 `id`
- `essays.university` / `essays.major`: 잡코리아 `spec_raw`에서 정규식 파싱, 링커리어는 API 직접 제공
- `qna.question_clean` / `qna.answer_clean` / `qna.question_type` / `qna.is_valid`: **전처리 담당이 별도 스크립트로 UPDATE 예정** — 크롤러 단계에서는 NULL로 두면 됨
- `qna_embeddings`: **임베딩 담당이 채움** — 크롤러·전처리 단계에서는 건드리지 않아도 됨

---

## 4. 전처리 파이프라인

### 4-1. 전체 흐름

```
[SQLite DB: essays + qna (raw)]
         │
         ▼
  ① 오매칭 필터링 (is_valid = 0)
         │
         ▼
  ② 텍스트 정제 → answer_clean, question_clean
         │
         ▼
  ③ 최소 길이 필터 (is_valid = 0)
         │
         ▼
  ④ 링커리어 Q&A 분리 (source='linkareer' 인 경우)
         │
         ▼
  ⑤ 질문 유형 분류 → question_type
         │
         ▼
[SQLite DB: qna 컬럼 업데이트 완료]
         │
         ▼
  ⑥ BGE-M3 임베딩 → ChromaDB 적재
```

### 4-2. 단계별 세부 처리

#### ① 오매칭 필터링
- `COMPANY_ALIASES` 딕셔너리로 `company` 컬럼 재검증
- 기아 예시: `company`에 "기아타이거즈", "기아자동차부품" 등 포함 시 `is_valid = 0`

#### ② 텍스트 정제

```python
import re

def clean_text(text: str) -> str:
    # 줄 끝 공백 제거
    text = "\n".join(line.rstrip() for line in text.splitlines())
    # 3줄 이상 연속 빈줄 → 2줄로 압축
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 링커리어 홍보 문구 패턴 제거
    # (예: "안녕하세요 ○○에 지원한 ○○입니다" 형태의 도입부)
    text = re.sub(
        r'^[\s\S]{0,200}?(안녕하세요|지원하게\s*된|귀사에\s*지원)',
        '', text, count=1
    )
    # HTML 엔티티 잔재 제거
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    # 전각 공백 → 반각
    text = text.replace('　', ' ')
    return text.strip()
```

#### ③ 최소 길이 필터
- `len(answer_clean) < 50` 이면 `is_valid = 0` (의미 없는 단답 제거)
- 링커리어 Q&A 분리 후 조각도 동일 기준 적용

#### ④ 링커리어 Q&A 분리

링커리어 `content`는 단일 문자열로 Q&A가 혼합되어 있음.  
아래 패턴으로 분리:

```python
QA_SPLIT_PATTERN = re.compile(
    r'(?:^|\n)\s*'                          # 줄 시작
    r'(?:'
    r'Q\.?\s*\d+'                           # Q1, Q.1
    r'|【.*?】'                              # 【지원동기】
    r'|\[.*?\]'                             # [성장과정]
    r'|\d+\s*[\.、．]\s*[가-힣]'            # 1. 성장과정
    r'|[■◆▶◎]\s*[가-힣]'                  # ■ 지원동기
    r')',
    re.MULTILINE
)

def split_linkareer_qna(content: str) -> list[dict]:
    splits = list(QA_SPLIT_PATTERN.finditer(content))
    pairs = []
    for i, m in enumerate(splits):
        block_start = m.start()
        block_end   = splits[i+1].start() if i+1 < len(splits) else len(content)
        block       = content[block_start:block_end].strip()
        # 첫 줄이 질문, 나머지가 답변
        lines  = block.split('\n', 1)
        question = lines[0].strip()
        answer   = lines[1].strip() if len(lines) > 1 else ""
        pairs.append({"question": question, "answer": answer})
    # 패턴 미검출 시 전체를 하나의 답변으로 처리
    if not pairs:
        pairs = [{"question": "", "answer": content.strip()}]
    return pairs
```

#### ⑤ 질문 유형 분류

키워드 기반 룰 → 미분류 시 `"etc"`:

```python
QUESTION_TYPE_RULES: dict[str, list[str]] = {
    "growth":      ["성장", "어린 시절", "학창 시절", "살아오면서"],
    "motivation":  ["지원 동기", "지원하게", "왜 지원", "관심을 갖게"],
    "experience":  ["경험", "활동", "프로젝트", "인턴", "아르바이트"],
    "fit":         ["직무", "역량", "강점", "강점과 약점", "포부", "비전"],
    "personality": ["성격", "장단점", "단점", "특기"],
    "goal":        ["입사 후", "목표", "10년", "5년", "커리어"],
}

def classify_question_type(question: str) -> str:
    for qtype, keywords in QUESTION_TYPE_RULES.items():
        if any(kw in question for kw in keywords):
            return qtype
    return "etc"
```

---

## 5. 임베딩 설계 (BGE-M3)

### 5-1. 모델 선택 근거

| 항목 | 내용 |
|------|------|
| 모델 | `BAAI/bge-m3` |
| 차원 | 1,024 |
| 최대 토큰 | 8,192 (한국어 자소서 1건 완전 처리 가능) |
| 특징 | Dense + Sparse + ColBERT 동시 지원, 한국어 최강 |
| 추론 환경 | CUDA GPU 권장; CPU fallback 가능 |

### 5-2. 임베딩 단위

- **단위**: `qna` 테이블의 1행 (Q&A 쌍 1개)
- **입력 텍스트 구성**:
  ```
  [기업: 삼성전자] [직무: 소프트웨어개발자] [유형: experience]
  질문: {question_clean}
  답변: {answer_clean}
  ```
  → 검색 시 컨텍스트를 풍부하게 해 검색 품질 향상

### 5-3. 벡터 DB — ChromaDB

```python
import chromadb
from chromadb.config import Settings

client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_or_create_collection(
    name="coverletter_qna",
    metadata={"hnsw:space": "cosine"},     # 코사인 유사도
)
```

**저장 시 메타데이터 구조** (검색 필터용):

```python
{
    "qna_id":        1234,          # SQLite qna.id (역참조용)
    "essay_id":      56,
    "source":        "jobkorea",
    "company":       "삼성전자",
    "org_type":      "corp",
    "role":          "소프트웨어개발자",
    "question_type": "experience",
    "year":          "2023",
    "season":        "하반기",
    "char_count":    850,
}
```

### 5-4. 임베딩 적재 스크립트 구조

```python
# embed_pipeline.py (예정)
from FlagEmbedding import BGEM3FlagModel
import chromadb, sqlite3, math

model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
BATCH_SIZE = 64

def build_doc_text(row: dict) -> str:
    return (
        f"[기업: {row['company']}] "
        f"[직무: {row['role'] or ''}] "
        f"[유형: {row['question_type'] or ''}]\n"
        f"질문: {row['question_clean'] or row['question'] or ''}\n"
        f"답변: {row['answer_clean'] or row['answer']}"
    )

def embed_all(db_path: str):
    conn  = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows  = conn.execute("""
        SELECT q.id, q.essay_id, q.question, q.answer,
               q.question_clean, q.answer_clean, q.question_type,
               q.char_count, q.is_valid,
               e.company, e.source, e.org_type, e.role, e.year, e.season
        FROM qna q
        JOIN essays e ON e.id = q.essay_id
        WHERE q.is_valid = 1
          AND q.id NOT IN (SELECT qna_id FROM qna_embeddings)
    """).fetchall()

    client     = chromadb.PersistentClient(path="./chroma_db")
    collection = client.get_or_create_collection(
        "coverletter_qna", metadata={"hnsw:space": "cosine"}
    )

    for i in range(0, len(rows), BATCH_SIZE):
        batch    = rows[i : i + BATCH_SIZE]
        docs     = [build_doc_text(dict(r)) for r in batch]
        vecs     = model.encode(docs, batch_size=BATCH_SIZE)["dense_vecs"]
        ids      = [f"qna_{r['id']}" for r in batch]
        metas    = [{
            "qna_id": r["id"], "essay_id": r["essay_id"],
            "source": r["source"], "company": r["company"],
            "org_type": r["org_type"], "role": r["role"] or "",
            "question_type": r["question_type"] or "",
            "year": r["year"] or "", "season": r["season"] or "",
            "char_count": r["char_count"] or 0,
        } for r in batch]

        collection.add(ids=ids, embeddings=vecs.tolist(),
                       documents=docs, metadatas=metas)

        # SQLite 동기화
        conn.executemany(
            "INSERT OR IGNORE INTO qna_embeddings (qna_id, chroma_id, model_name, embedded_at) "
            "VALUES (?, ?, 'BAAI/bge-m3', datetime('now'))",
            [(r["id"], f"qna_{r['id']}") for r in batch],
        )
        conn.commit()
        print(f"  임베딩 완료: {i+len(batch)}/{len(rows)}")

    conn.close()
```

### 5-5. 검색 예시 (RAG 단계 참고)

```python
def search_similar(
    query: str,
    company: str,
    question_type: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    q_vec = model.encode([query])["dense_vecs"][0].tolist()

    where = {"company": company}
    if question_type:
        where["question_type"] = question_type

    results = collection.query(
        query_embeddings=[q_vec],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return results
```

---

## 6. 역할 분담 요약

| 역할 | 담당 | 내용 |
|------|------|------|
| DB 구조 구현 | **팀원** | 위 3-2 스키마 그대로 `init_db()` 함수 작성 |
| 잡코리아 크롤러 | 나 | `crawler.py` (완성) |
| 링커리어 크롤러 | 나 | `crawler_linkareer.py` (작성 예정) |
| 전처리 스크립트 | 나 | `preprocess.py` — 4절 파이프라인 구현 |
| 임베딩 스크립트 | 나 | `embed_pipeline.py` — 5절 구현 |
| RAG + 프롬프트 | 추후 결정 | Sprint 4 |
| UI | 추후 결정 | Sprint 5 |

---

## 7. 예상 일정 (Sprint 기준)

| Sprint | 목표 | 산출물 |
|--------|------|--------|
| S1 (수집) | 잡코리아·링커리어 크롤링 완료 | `jobkorea_essays.db`, `linkareer_essays.db` → 통합 DB |
| S2 (전처리) | 전처리 + 질문 유형 분류 완료 | `preprocess.py`, `qna.question_clean` 등 업데이트 |
| S3 (임베딩) | BGE-M3 임베딩 + ChromaDB 적재 | `embed_pipeline.py`, `chroma_db/` |
| S4 (RAG) | 유사 자소서 검색 + Claude API 첨삭 | `rag.py`, `feedback_prompt.py` |
| S5 (UI) | Streamlit 또는 FastAPI 기반 서비스 | `app.py` |
