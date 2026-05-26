# 합격자소서 RAG 첨삭 시스템

합격자소서 데이터 수집 → 전처리 → 임베딩 → GPT 기반 자소서 첨삭까지의 End-to-End 파이프라인

---

## 디렉토리 구조

```
binesses_intellegence_4-/
│
├── 📥 crawling/
│   ├── crawler.py            # 잡코리아 합격자소서 크롤러
│   ├── crawler_linkareer.py  # 링커리어 합격자소서 크롤러
│   └── db.py                 # SQLite 스키마 및 저장 유틸리티
│
├── 🔧 preprocessing/
│   └── preprocess.py         # 텍스트 정제 · Q&A 분리 · 질문 유형 분류
│
├── 🧮 embedding/
│   ├── embed_pipeline.py     # BGE-M3 임베딩 → ChromaDB 저장
│   └── colab_embed.ipynb     # Google Colab GPU 임베딩 노트북
│
├── 🤖 ai/
│   ├── search.py             # RAG 검색 (ChromaDB ↔ BGE-M3)
│   ├── advisor.py            # 첨삭 메인 로직 (OpenAI GPT-4o-mini)
│   ├── prompt.py             # 시스템 프롬프트 및 유저 프롬프트 빌더
│   └── jd_data.py            # 기업별 JD · 인재상 데이터베이스
│
├── 💻 cli/
│   └── app.py                # 자소서 첨삭 CLI (대화형 / 데모 모드)
│
├── export_data.py            # essays.db + ChromaDB → CSV 내보내기
├── requirements.txt          # 패키지 의존성
├── .env.example              # API 키 설정 템플릿
└── README.md
```

> `essays.db`, `chroma_db/`, `.env` 는 `.gitignore`에 포함 — **절대 커밋하지 마세요**  
> 데이터 공유는 아래 [데이터 공유](#데이터-공유) 섹션 참고

---

## ⚡ 빠른 시작 (팀원용)

> 크롤링·임베딩 없이 **기존 데이터로 바로 첨삭 CLI를 실행**하는 방법입니다.

### 1단계 — 레포 클론

```bash
git clone https://github.com/hochang2/binesses_intellegence_4-.git
cd binesses_intellegence_4-
```

### 2단계 — 패키지 설치

```bash
pip install -r requirements.txt
```

> Python 3.10 이상 권장. 가상환경 사용 시:
> ```bash
> python -m venv venv
> # Windows
> venv\Scripts\activate
> # Mac/Linux
> source venv/bin/activate
> pip install -r requirements.txt
> ```

### 3단계 — API 키 설정

```bash
# .env.example 복사 후 키 입력
copy .env.example .env        # Windows
# cp .env.example .env        # Mac/Linux
```

`.env` 파일을 열고 OpenAI API 키 입력:
```
OPENAI_API_KEY=sk-proj-여기에_실제_키_입력
```

### 4단계 — 데이터 파일 배치

`essays.db`와 `chroma_db/`는 git에 포함되지 않으므로 팀원에게 직접 받아야 합니다.

```
binesses_intellegence_4-/   ← 프로젝트 루트
├── essays.db               ← 여기에 배치
├── chroma_db/              ← 여기에 배치 (폴더째로)
│   ├── chroma.sqlite3
│   └── 8ca0be17-.../
└── ...
```

| 파일 | 받는 방법 |
|------|----------|
| `essays.db` | 팀원에게 파일 직접 전달 |
| `chroma_db/` (약 205MB) | zip으로 압축 후 구글 드라이브/카카오톡 전달 → 프로젝트 루트에 압축 해제 |

> **chroma_db가 없는 경우**: `qna.csv`를 받아서 임베딩을 새로 생성할 수 있습니다. ([임베딩 섹션](#3-임베딩) 참고)

### 5단계 — 첨삭 CLI 실행

```bash
# Windows (한글 깨짐 방지)
python -X utf8 cli/app.py --demo

# Mac/Linux
python cli/app.py --demo
```

정상 실행 시 삼성전자 성장과정 데모 첨삭 결과가 출력됩니다.

```bash
# 직접 입력 모드
python -X utf8 cli/app.py

# 인자로 바로 실행
python -X utf8 cli/app.py --company 삼성전자 --question "지원동기를 기술하시오." --draft "저는..."

# JSON 형식 출력
python -X utf8 cli/app.py --demo --json
```

---

## 수집 대상 기업 (12개)

| 유형 | 기업 |
|------|------|
| 대기업 | 삼성전자, 현대자동차, SK하이닉스, LG전자, 포스코 |
| 공공기관 | 한국전력 |
| 은행 | 농협은행, 기업은행, 신한은행, 우리은행, 국민은행, 하나은행 |

---

## 실행 순서

### 0. 환경 설정

```bash
pip install -r requirements.txt
```

`.env` 파일 생성 (`.env.example` 복사):
```bash
cp .env.example .env
# .env 열고 OPENAI_API_KEY 입력
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

**로컬 (CPU)**
```bash
python embedding/embed_pipeline.py

# 테스트 (100건만)
python embedding/embed_pipeline.py --test
```

**Google Colab (GPU 권장)**  
`embedding/colab_embed.ipynb`를 Colab에서 열고 T4 GPU 런타임으로 실행합니다.

### 4. 자소서 첨삭 CLI

```bash
# 데모 모드 (삼성전자 성장과정 예시)
python -X utf8 cli/app.py --demo

# 대화형 입력
python -X utf8 cli/app.py

# 인자 지정
python -X utf8 cli/app.py --company 삼성전자 --question "지원동기를 기술하시오." --draft "저는..."
```

---

## 데이터 공유

`essays.db`와 `chroma_db/`는 `.gitignore` 처리되어 있어 git에 올라가지 않습니다.  
아래 스크립트로 CSV로 내보내 팀원과 공유하세요.

```bash
python export_data.py
```

| 파일 | 내용 |
|------|------|
| `data/essays.csv` | 자소서 메타데이터 (기업, 직무, 연도 등) |
| `data/qna.csv` | Q&A 쌍 + 기업 정보 join (임베딩 핵심 데이터) |
| `data/chroma_docs.csv` | ChromaDB 저장 문서 + 메타데이터 (벡터 제외) |

> **ChromaDB 재구축**: `chroma_docs.csv`를 받은 후 `embedding/embed_pipeline.py`를 실행하면 벡터 인덱스를 재생성할 수 있습니다.

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
| `jd_used` | JD 데이터 사용 여부 |

---

## 임베딩 모델

- **모델**: `BAAI/bge-m3` (dense 1024차원, cosine 유사도)
- **저장**: ChromaDB PersistentClient (`./chroma_db`)
- **메타데이터**: `company`, `org_type`, `role`, `question_type`, `char_count` 등
