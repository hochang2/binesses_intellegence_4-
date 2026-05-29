# 합격자소서 RAG 첨삭 시스템

합격자소서 데이터 수집 → 전처리 → 임베딩 → GPT 기반 자소서 첨삭까지의 End-to-End 파이프라인

---

## 현재 데이터 규모

| 항목 | 수치 |
|------|------|
| 수집 기업 | 12개 (대기업 5 / 공공기관 1 / 은행 6) |
| 합격자소서 벡터 수 | 12,069개 |
| 데이터 출처 | 잡코리아 + 링커리어 |
| 임베딩 모델 | BAAI/bge-m3 (1024차원, cosine) |
| 첨삭 모델 | GPT-4o-mini |

**수집 기업 목록**

| 유형 | 기업 |
|------|------|
| 대기업 | 삼성전자, 현대자동차, SK하이닉스, LG전자, 포스코 |
| 공공기관 | 한국전력 |
| 은행 | 농협은행, 기업은행, 신한은행, 우리은행, 국민은행, 하나은행 |

---

## 디렉토리 구조

```
binesses_intellegence_4-/
│
├── 📥 crawling/
│   ├── crawler.py              # 잡코리아 합격자소서 크롤러
│   ├── crawler_linkareer.py    # 링커리어 합격자소서 크롤러
│   └── db.py                   # SQLite 스키마 및 저장 유틸리티
│
├── 🔧 preprocessing/
│   └── preprocess.py           # 텍스트 정제 · Q&A 분리 · 질문 유형 분류
│
├── 🧮 embedding/
│   ├── embed_pipeline.py       # BGE-M3 임베딩 → ChromaDB 저장
│   └── colab_embed.ipynb       # Google Colab GPU 임베딩 노트북
│
├── 🤖 ai/
│   ├── search.py               # RAG 검색 (ChromaDB + BGE-M3)
│   ├── advisor.py              # 첨삭 메인 로직 (OpenAI GPT-4o-mini)
│   ├── prompt.py               # 시스템/유저 프롬프트 빌더
│   └── jd_data.py              # 기업별 JD · 인재상 데이터베이스
│
├── 💻 cli/
│   └── app.py                  # 자소서 첨삭 CLI (대화형 / 인자 지정)
│
├── demo.py                     # 기업 선택 메뉴 데모 (권장)
├── test_rag.py                 # RAG 검색 + 첨삭 통합 테스트 스크립트
├── export_data.py              # essays.db + ChromaDB → CSV 내보내기
├── generate_examples.py        # 기업별 예시 자소서 JSON 생성
├── requirements.txt            # 패키지 의존성
└── .env.example                # API 키 설정 템플릿
```

> `essays.db`, `chroma_db/`, `.env` 는 `.gitignore` 처리 — **절대 커밋하지 마세요**

---

## ⚡ 빠른 시작 (팀원용)

> 크롤링·임베딩 없이 **기존 데이터로 바로 첨삭 데모를 실행**하는 방법입니다.

### 1단계 — 레포 클론

```bash
git clone https://github.com/hochang2/binesses_intellegence_4-.git
cd binesses_intellegence_4-
```

### 2단계 — 가상환경 생성 및 패키지 설치

> ⚠️ **chromadb 버전 충돌 문제** 때문에 Python 3.10 전용 가상환경(`venv_chroma`)을 따로 사용합니다.

```bash
# Python 3.10으로 가상환경 생성 (py 런처 사용 시)
py -3.10 -m venv venv_chroma

# Windows 활성화
venv_chroma\Scripts\activate

# 패키지 설치
pip install -r requirements.txt
```

Python 3.10이 없는 경우 [Python 3.10 다운로드](https://www.python.org/downloads/release/python-31011/)

### 3단계 — API 키 설정

```bash
# Windows
copy .env.example .env
```

`.env` 파일을 열고 OpenAI API 키 입력:

```
OPENAI_API_KEY=sk-proj-여기에_실제_키_입력
```

### 4단계 — 데이터 파일 배치

`essays.db`와 `chroma_db/`는 git에 포함되지 않으므로 팀원에게 직접 받아야 합니다.

```
binesses_intellegence_4-/
├── essays.db         ← 여기에 배치
├── chroma_db/        ← 여기에 배치 (폴더째로)
│   ├── chroma.sqlite3
│   └── 7b6eba5c-.../
└── ...
```

| 파일 | 받는 방법 |
|------|----------|
| `essays.db` | 팀원에게 직접 전달 |
| `chroma_db/` (약 200MB) | zip 압축 후 구글 드라이브 / 카카오톡 전달 → 프로젝트 루트에 압축 해제 |

### 5단계 — 데모 실행

```bash
# 가상환경 활성화 상태에서 실행
python demo.py                    # 기업 선택 메뉴
python demo.py --company 삼성전자 # 특정 기업 바로 실행
python demo.py --all              # 전체 기업 순서대로
```

---

## 실행 순서 (처음부터 구축하는 경우)

### 0. 환경 설정

```bash
py -3.10 -m venv venv_chroma
venv_chroma\Scripts\activate      # Windows
pip install -r requirements.txt
cp .env.example .env              # API 키 입력
```

### 1. 크롤링

```bash
python crawling/crawler.py            # 잡코리아
python crawling/crawler_linkareer.py  # 링커리어
```

중단 후 재시작해도 이미 수집한 항목은 자동 스킵됩니다.

### 2. 전처리

```bash
python preprocessing/preprocess.py

# 테스트만 (DB 수정 없음)
python preprocessing/preprocess.py --dry-run
```

| 질문 유형 | 키워드 |
|-----------|--------|
| `growth` | 성장과정, 학창시절 |
| `motivation` | 지원동기, 관심을 갖게 |
| `experience` | 경험, 프로젝트, 인턴 |
| `fit` | 직무역량, 강점, 포부 |
| `personality` | 성격, 장단점 |
| `goal` | 입사 후 목표, 10년 후 |

### 3. 임베딩

**로컬 (CPU, 약 40분)**

```bash
python embedding/embed_pipeline.py

# 테스트 (100건만)
python embedding/embed_pipeline.py --test
```

**Google Colab (GPU 권장, 약 5분)**

`embedding/colab_embed.ipynb`를 Colab에서 열고 T4 GPU 런타임으로 실행합니다.

### 4. 첨삭 실행

```bash
# 데모 (기업 선택 메뉴)
python demo.py

# CLI (직접 입력)
python cli/app.py

# CLI (인자 지정)
python cli/app.py --company 삼성전자 --question "지원동기를 기술하시오." --draft "저는..."
```

---

## 테스트 스크립트

```bash
# RAG 검색 테스트 (빠름, API 호출 없음)
python test_rag.py

# 필터 검색 테스트 포함
python test_rag.py --filters

# 전체 첨삭 파이프라인 테스트 (OpenAI 호출, 유료)
python test_rag.py --full --company 삼성전자

# ChromaDB 벡터 수 확인
python test_rag.py --company 하나은행
```

---

## AI 첨삭 흐름

```
[사용자 입력: 초안 + 문항 + 기업명]
         │
         ▼
  ① 3단계 fallback RAG 검색
     기업 필터 → 업종(org_type) → 전체
         │
         ▼
  ② 프롬프트 구성
     참고자소서 (평균 글자수 포함) + 기업 JD/인재상
         │
         ▼
  ③ OpenAI GPT-4o-mini 호출
     JSON 응답 (summary, pros, cons, rewrite)
         │
         ▼
  ④ 결과 출력
     원본 초안 | 총평 | 잘된 점 | 개선 필요 | 수정 자소서
```

| 응답 필드 | 내용 |
|-----------|------|
| `summary` | 초안 전체 총평 (2~3문장) |
| `pros` | 잘된 점 리스트 |
| `cons` | 개선 필요 리스트 (point / reason / suggestion) |
| `rewrite` | 수정 자소서 전문 (참고자소서 평균 글자수 기준) |
| `references` | 참고한 합격자소서 목록 (유사도, 글자수) |
| `ref_warning` | True = 해당 기업 데이터 없어 fallback 사용 |
| `jd_used` | JD 데이터 사용 여부 |

---

## 데이터 공유

`essays.db`와 `chroma_db/`는 `.gitignore` 처리되어 있습니다.
아래 스크립트로 CSV로 내보내 팀원과 공유하세요.

```bash
python export_data.py
```

| 파일 | 내용 |
|------|------|
| `data/essays.csv` | 자소서 메타데이터 (기업, 직무, 연도 등) |
| `data/qna.csv` | Q&A 쌍 + 기업 정보 join |
| `data/chroma_docs.csv` | ChromaDB 저장 문서 + 메타데이터 |

---

## 기술 스택

| 역할 | 도구 |
|------|------|
| 크롤링 | requests, BeautifulSoup, Selenium |
| 데이터 저장 | SQLite (essays.db) |
| 임베딩 모델 | BAAI/bge-m3 (sentence-transformers) |
| 벡터 DB | ChromaDB 0.6.x (Python 3.10 전용) |
| LLM | OpenAI GPT-4o-mini |
| 환경 | Python 3.10, venv_chroma |
