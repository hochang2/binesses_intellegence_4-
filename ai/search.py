"""
RAG 검색 유틸리티
- ChromaDB 에서 유사 자소서 Q&A 검색
- 사용: python search.py
- 또는 import 해서 retrieve() 함수 직접 호출
"""

import logging
import os
import re
import sys
from pathlib import Path

# ChromaDB 텔레메트리 / HuggingFace 불필요한 경고 억제
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")           # huggingface_hub >= 1.x
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# chromadb 텔레메트리 로거 비활성화 (0.6.x 내부 버그로 stderr 에 오류 출력하는 문제)
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

# 프로젝트 루트를 Python 경로에 추가
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# chroma_db는 프로젝트 루트 기준 절대 경로
CHROMA_PATH = str(_ROOT / "chroma_db")
COLLECTION  = "cover_letters"
MODEL_NAME  = "BAAI/bge-m3"

# 크롤링 아티팩트 제거 패턴 (LLM 에 넘기기 전 참고 답변 정제용)
_NOISE_RE = re.compile(
    r"^\(\d+자[^)\n]*(?:\([^)\n]*\))?\)\s*\n*"  # (700자), (700자 이내 (영문 1400자)) 등
    r"|\b\d+자\s+이내[^\n]*\n*"                  # 700자 이내 ... (괄호 없는 형태)
    r"|^Guide>\s*\n*"                            # Guide> 헤더
    r"|^\[[^\]\n]{1,20}\]\s*\n",                 # [가이드라인] 한 줄 헤더
    re.MULTILINE,
)


# ── 모델 / 컬렉션 (싱글톤) ───────────────────────────────────────────────────

_model = None
_col   = None

def _clean_ref_answer(text: str) -> str:
    """크롤링 아티팩트(글자수 표기, Guide> 등)를 제거한 깔끔한 답변 반환."""
    text = _NOISE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_model():
    global _model
    if _model is None:
        print(f"[검색] BGE-M3 모델 로딩 중... (첫 실행 시 15~20초 소요)", flush=True)
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
        print("[검색] 모델 로딩 완료", flush=True)
    return _model

def _get_col():
    global _col
    if _col is None:
        import chromadb
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
        _col = client.get_collection(COLLECTION)
    return _col


# ── 핵심 검색 함수 ────────────────────────────────────────────────────────────

def retrieve(
    query: str,
    *,
    company:       str | None = None,   # 기업 필터 (exact match)
    org_type:      str | None = None,   # 'corp' | 'bank' | 'public'
    question_type: str | None = None,   # 'experience' | 'motivation' | ...
    n_results:     int        = 5,
) -> list[dict]:
    """
    query 텍스트와 유사한 합격 자소서 Q&A 반환.

    Parameters
    ----------
    query         : 사용자 초안 또는 질문 텍스트
    company       : 지원 기업 (예: '삼성전자') — None이면 필터 없음
    org_type      : 기업 유형 필터
    question_type : 질문 유형 필터
    n_results     : 반환 개수

    Returns
    -------
    list[dict]  각 항목:
        company, role, question_type, question, answer,
        char_count, source, similarity
    """
    model = _get_model()
    col   = _get_col()

    # 쿼리 임베딩
    vec = model.encode([query], normalize_embeddings=True)[0].tolist()

    # 메타데이터 필터 조합
    where_clauses = []
    if company:
        where_clauses.append({"company": {"$eq": company}})
    if org_type:
        where_clauses.append({"org_type": {"$eq": org_type}})
    if question_type:
        where_clauses.append({"question_type": {"$eq": question_type}})

    where = None
    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}

    # ChromaDB 검색
    kwargs = dict(
        query_embeddings=[vec],
        n_results=n_results,
        include=["metadatas", "documents", "distances"],
    )
    if where:
        kwargs["where"] = where

    res = col.query(**kwargs)

    # 결과 정리
    results = []
    for meta, doc, dist in zip(
        res["metadatas"][0],
        res["documents"][0],
        res["distances"][0],
    ):
        # ChromaDB cosine distance = 1 - cosine_similarity
        similarity = round(1 - dist, 4)

        # documents 에 저장된 텍스트에서 Q/A 분리 후 노이즈 제거
        parts    = doc.split("\n", 1)
        question = parts[0] if len(parts) == 2 else ""
        answer   = _clean_ref_answer(parts[1] if len(parts) == 2 else parts[0])

        results.append({
            "company":       meta.get("company", ""),
            "role":          meta.get("role", ""),
            "question_type": meta.get("question_type", ""),
            "source":        meta.get("source", ""),
            "year":          meta.get("year", ""),
            "season":        meta.get("season", ""),
            "question":      question,
            "answer":        answer,
            "char_count":    meta.get("char_count", 0),
            "similarity":    similarity,
            "qna_id":        meta.get("qna_id", 0),
        })

    return results


def print_results(results: list[dict]) -> None:
    """검색 결과 콘솔 출력"""
    for i, r in enumerate(results, 1):
        print(f"\n{'─'*60}")
        print(f"[{i}] {r['company']} / {r['role'] or '직무미상'} ({r['source']})")
        print(f"     유형={r['question_type']}  유사도={r['similarity']:.4f}  {r['year']}{r['season']}")
        if r["question"]:
            print(f"  Q: {r['question'][:80]}")
        print(f"  A: {r['answer'][:200]}{'...' if len(r['answer'])>200 else ''}")


# ── CLI 테스트 ────────────────────────────────────────────────────────────────

def _interactive_test():
    import argparse
    parser = argparse.ArgumentParser(description="합격 자소서 RAG 검색")
    parser.add_argument("query", nargs="?", help="검색할 텍스트 (없으면 예시 실행)")
    parser.add_argument("--company",       default=None)
    parser.add_argument("--org_type",      default=None, choices=["corp","bank","public"])
    parser.add_argument("--question_type", default=None,
                        choices=["experience","motivation","fit","growth","personality","goal","etc"])
    parser.add_argument("-n", type=int, default=5)
    args = parser.parse_args()

    # 예시 쿼리
    query = args.query or "팀 프로젝트에서 갈등을 해결하고 목표를 달성한 경험을 서술하시오."

    print(f"\n검색어: {query!r}")
    print(f"필터  : company={args.company}  org_type={args.org_type}  question_type={args.question_type}")
    print(f"결과수: {args.n}개\n")

    results = retrieve(
        query,
        company=args.company,
        org_type=args.org_type,
        question_type=args.question_type,
        n_results=args.n,
    )
    print_results(results)


if __name__ == "__main__":
    _interactive_test()
