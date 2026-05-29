"""
자소서 첨삭 RAG 테스트 스크립트

실행:
    python test_rag.py              # RAG 검색만 (빠름, API 호출 없음)
    python test_rag.py --full       # 첨삭까지 전체 (OpenAI 호출, 유료)
    python test_rag.py --company 삼성전자  # 특정 기업 필터 + 첨삭
    python test_rag.py --query "나만의 텍스트"   # 커스텀 쿼리 검색

환경:
    venv_chroma 가상환경에서 실행 필요
    (start_venv.ps1 또는 activate.bat 으로 가상환경 먼저 활성화)
"""

import os
import sys
import time
import argparse
from pathlib import Path

# 경고 억제는 chromadb/HF 가 import 되기 전에 설정해야 함
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN_WARNING", "1")

# 프로젝트 루트를 경로에 추가
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SEP  = "=" * 64
THIN = "-" * 64

# ── 예시 초안 (테스트용) ──────────────────────────────────────────────────────

SAMPLE_DRAFTS = {
    "삼성전자": {
        "question": "삼성전자를 지원한 이유와 입사 후 이루고 싶은 목표를 서술하시오.",
        "draft": (
            "저는 삼성전자의 글로벌 경쟁력과 기술 혁신에 매력을 느껴 지원했습니다. "
            "학부 시절 반도체 공정 수업을 들으며 메모리 설계에 흥미를 가졌고, "
            "팀 프로젝트에서 DRAM 구조를 직접 분석한 경험이 있습니다. "
            "입사 후에는 D램 선행 연구 부서에서 차세대 공정 개발에 기여하고 싶습니다."
        ),
    },
    "하나은행": {
        "question": "지원 동기 및 입행 후 이루고자 하는 목표를 작성하시오.",
        "draft": (
            "하나은행의 디지털 금융 혁신 노력에 공감하여 지원하게 되었습니다. "
            "금융 동아리에서 2년간 활동하며 PB 서비스와 자산 관리에 관심을 키웠고, "
            "관련 자격증(AFPK)도 취득하였습니다. "
            "입행 후에는 개인금융 부서에서 고객 맞춤형 자산 관리 서비스를 제공하는 "
            "전문 PB로 성장하고 싶습니다."
        ),
    },
    "기본": {
        "question": "팀 프로젝트에서 갈등을 해결하고 목표를 달성한 경험을 서술하시오.",
        "draft": (
            "대학 졸업 프로젝트에서 팀원들과 개발 방향성 차이로 갈등이 생겼습니다. "
            "저는 중간 역할을 맡아 각자의 의견을 정리하고 회의를 진행했습니다. "
            "결국 모두가 납득할 수 있는 방향으로 합의했고 프로젝트를 성공적으로 완료했습니다."
        ),
    },
}


# ── 단계 1: ChromaDB 연결 테스트 ──────────────────────────────────────────────

def test_chroma_connection():
    print(f"\n{SEP}")
    print("  [1단계] ChromaDB 연결 & 벡터 수 확인")
    print(SEP)
    t0 = time.time()
    try:
        from ai.search import _get_col   # search.py 싱글톤 재사용 (충돌 방지)
        col = _get_col()
        count = col.count()
        elapsed = time.time() - t0
        print(f"  컬렉션: cover_letters")
        print(f"  저장된 벡터 수: {count:,}개")
        print(f"  연결 시간: {elapsed:.2f}초")
        print(f"  결과: OK")
        return col
    except Exception as e:
        print(f"  [오류] ChromaDB 연결 실패: {e}")
        sys.exit(1)


# ── 단계 2: RAG 검색 테스트 ──────────────────────────────────────────────────

def test_rag_search(query: str, company: str | None, n: int = 5):
    print(f"\n{SEP}")
    print("  [2단계] RAG 검색 테스트 (BGE-M3 임베딩)")
    print(SEP)
    print(f"  쿼리: {query[:80]}{'...' if len(query)>80 else ''}")
    if company:
        print(f"  기업 필터: {company}")
    print(f"  요청 개수: {n}개\n")

    t0 = time.time()
    try:
        from ai.search import retrieve, print_results
        results = retrieve(query, company=company, n_results=n)
        elapsed = time.time() - t0

        if not results:
            print("  [주의] 검색 결과 없음 — company 필터를 제거하거나 다른 쿼리를 시도하세요.")
            return results

        print_results(results)
        print(f"\n  검색 완료: {len(results)}건  ({elapsed:.2f}초)")
        print(f"  유사도 범위: {results[-1]['similarity']:.4f} ~ {results[0]['similarity']:.4f}")
        return results

    except Exception as e:
        print(f"  [오류] RAG 검색 실패: {e}")
        import traceback; traceback.print_exc()
        return []


# ── 단계 3: 전체 첨삭 파이프라인 테스트 ─────────────────────────────────────

def test_full_advise(draft: str, question: str, company: str):
    print(f"\n{SEP}")
    print("  [3단계] 전체 첨삭 파이프라인 (OpenAI GPT)")
    print(SEP)
    print(f"  기업: {company}")
    print(f"  문항: {question[:60]}{'...' if len(question)>60 else ''}")
    print(f"  초안: {draft[:80]}...\n")

    t0 = time.time()
    try:
        from ai.advisor import advise
        result = advise(draft=draft, question=question, company=company)
        elapsed = time.time() - t0

        print(f"\n{THIN}")
        print(f"  총평: {result['summary']}")

        print(f"\n  잘된 점:")
        for i, p in enumerate(result.get("pros", []), 1):
            print(f"    {i}. {p}")

        print(f"\n  개선 필요:")
        for i, c in enumerate(result.get("cons", []), 1):
            if isinstance(c, dict):
                print(f"    {i}. [{c.get('point','')}]")
                print(f"       이유: {c.get('reason','')}")
                print(f"       제안: {c.get('suggestion','')}")

        rewrite = result.get("rewrite", "")
        if rewrite:
            avg = result.get("avg_ref_chars", 0)
            diff = len(rewrite) - avg
            sign = "+" if diff >= 0 else ""
            info = f"{len(rewrite)}자"
            if avg:
                info += f"  (참고평균 {avg}자 대비 {sign}{diff}자)"
            print(f"\n  수정 자소서 ({info}):")
            print(f"  {THIN[:56]}")
            for line in rewrite.split("\n"):
                print(f"  {line}")

        refs = result.get("references", [])
        warn = " (유사기업/전체 fallback)" if result.get("ref_warning") else ""
        print(f"\n  참고 자소서: {len(refs)}건{warn}")
        for i, r in enumerate(refs, 1):
            print(f"    [{i}] {r['company']} / {r.get('role') or '직무미상'}  유사도={r['similarity']:.4f}")

        print(f"\n{THIN}")
        jd_flag = "JD 있음" if result.get("jd_used") else "JD 없음"
        print(f"  초안 {result['input_chars']}자 → 수정본 {result.get('rewrite_chars',0)}자  |  {jd_flag}  |  토큰 {result['tokens_used']}  |  {result['model']}  ({elapsed:.1f}초)")
        print(f"  완료: OK")

    except Exception as e:
        print(f"  [오류] 첨삭 실패: {e}")
        import traceback; traceback.print_exc()


# ── 단계 4: 다양한 필터 검색 ─────────────────────────────────────────────────

def test_filter_search():
    print(f"\n{SEP}")
    print("  [4단계] 메타데이터 필터 검색 테스트")
    print(SEP)

    from ai.search import retrieve

    filters = [
        {"label": "은행권 (bank) 동기 유형",  "kwargs": {"org_type": "bank",   "question_type": "motivation", "n_results": 3}},
        {"label": "대기업 (corp) 경험 유형",   "kwargs": {"org_type": "corp",   "question_type": "experience", "n_results": 3}},
        {"label": "삼성전자 전체",              "kwargs": {"company":  "삼성전자",                             "n_results": 3}},
    ]

    query = "입사 후 목표와 지원 동기를 서술하시오."

    for f in filters:
        print(f"\n  필터: {f['label']}")
        try:
            results = retrieve(query, **f["kwargs"])
            if results:
                for r in results:
                    print(f"    · {r['company']:8s} | {r['question_type']:12s} | 유사도={r['similarity']:.4f} | {r['answer'][:40]}...")
            else:
                print("    (결과 없음)")
        except Exception as e:
            print(f"    [오류] {e}")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="자소서 첨삭 RAG 테스트")
    parser.add_argument("--full",    action="store_true", help="OpenAI 첨삭까지 전체 실행 (유료)")
    parser.add_argument("--company", default=None,        help="테스트할 기업명 (예: 삼성전자)")
    parser.add_argument("--query",   default=None,        help="커스텀 검색 쿼리")
    parser.add_argument("-n",        type=int, default=5, help="검색 결과 수 (기본 5)")
    parser.add_argument("--filters", action="store_true", help="메타데이터 필터 테스트도 실행")
    args = parser.parse_args()

    print(f"\n{SEP}")
    print("  합격자소서 RAG 첨삭 시스템 — 테스트 실행기")
    print(SEP)

    # 1단계: ChromaDB 연결
    test_chroma_connection()

    # 예시 선택
    if args.company and args.company in SAMPLE_DRAFTS:
        sample = SAMPLE_DRAFTS[args.company]
    elif args.company:
        sample = {**SAMPLE_DRAFTS["기본"], "company": args.company}
    else:
        sample = SAMPLE_DRAFTS["기본"]

    company  = args.company or "기본"
    question = sample["question"]
    draft    = sample["draft"]
    query    = args.query or f"{question}\n{draft}"

    # 2단계: RAG 검색
    test_rag_search(
        query=query,
        company=args.company,
        n=args.n,
    )

    # 4단계 (선택): 필터 검색
    if args.filters:
        test_filter_search()

    # 3단계 (선택): 전체 첨삭 (OpenAI 호출)
    if args.full:
        if args.company is None:
            company = "삼성전자"
            sample  = SAMPLE_DRAFTS["삼성전자"]
        test_full_advise(
            draft=sample["draft"],
            question=sample["question"],
            company=company,
        )
    else:
        print(f"\n{THIN}")
        print("  --full 플래그 없이 실행했으므로 OpenAI 첨삭 단계는 건너뜁니다.")
        print("  전체 테스트: python test_rag.py --full")
        print("  특정 기업:   python test_rag.py --full --company 삼성전자")

    print(f"\n{SEP}")
    print("  테스트 완료")
    print(SEP + "\n")


if __name__ == "__main__":
    main()
