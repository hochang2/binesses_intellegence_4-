"""
자소서 첨삭 CLI

사용 예시:
    python app.py --demo
    python app.py --company 삼성전자 --question "성장과정을 기술하시오." --draft "나는..."
    python app.py --demo --json        # JSON 그대로 출력
    python app.py                      # 대화형 입력
"""

import argparse
import json
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Windows 콘솔 UTF-8 강제 (더블클릭 실행 시에도 한글 깨짐 방지)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 데모 데이터 ───────────────────────────────────────────────────────────────

DEMO_COMPANY  = "삼성전자"
DEMO_QUESTION = (
    "본인의 성장과정을 간략히 기술하되 현재의 자신에게 가장 큰 영향을 끼친 "
    "사건, 인물 등을 포함하여 기술하시기 바랍니다."
)
DEMO_DRAFT = """\
어린 시절부터 전자기기를 분해하고 조립하는 것을 즐겼습니다.
중학교 때 고장난 컴퓨터를 직접 고쳐 가족들에게 선물했던 기억이
저를 공학도의 길로 이끌었습니다. 대학에서 전자공학을 전공하며
반도체 설계 과목에 특히 흥미를 느꼈고, 교수님 연구실에서
메모리 소자 관련 프로젝트에 참여하며 실무 역량을 키웠습니다.\
"""


# ── 출력 헬퍼 ────────────────────────────────────────────────────────────────

def _print_result(result: dict) -> None:
    """첨삭 결과를 보기 좋게 터미널에 출력"""
    sep  = "=" * 62
    thin = "─" * 62

    print(f"\n{sep}")
    print("  📋 자소서 첨삭 결과")
    print(sep)

    # 원본 초안
    draft = result.get("draft", "")
    if draft:
        print(f"\n📄 원본 초안 ({result['input_chars']}자)")
        print(f"   {'─'*56}")
        for line in draft.split("\n"):
            print(f"   {line}")
        print(f"   {'─'*56}")

    # 총평
    print(f"\n📝 총평")
    print(f"   {result['summary']}")

    # 잘된 점
    print(f"\n✅ 잘된 점")
    if result["pros"]:
        for i, p in enumerate(result["pros"], 1):
            print(f"   {i}. {p}")
    else:
        print("   (없음)")

    # 개선 필요
    print(f"\n⚠️  개선 필요")
    if result["cons"]:
        for i, c in enumerate(result["cons"], 1):
            if isinstance(c, dict):
                print(f"   {i}. [{c.get('point', '')}]")
                print(f"      이유: {c.get('reason', '')}")
                print(f"      제안: {c.get('suggestion', '')}")
            else:
                print(f"   {i}. {c}")
    else:
        print("   (없음)")

    # 수정 자소서 전문
    rewrite = result.get("rewrite", "")
    if rewrite:
        # HTML 태그 제거 (GPT가 간혹 <br> 등을 쓰는 경우 대비)
        import re as _re
        rewrite = _re.sub(r"<br\s*/?>", "\n", rewrite, flags=_re.IGNORECASE)
        rewrite = _re.sub(r"<[^>]+>", "", rewrite)
        rewrite_chars  = result.get("rewrite_chars", len(rewrite))
        avg_ref_chars  = result.get("avg_ref_chars", 0)
        char_info = f"{rewrite_chars}자"
        if avg_ref_chars:
            diff = rewrite_chars - avg_ref_chars
            sign = "+" if diff >= 0 else ""
            char_info += f"  (참고자소서 평균 {avg_ref_chars}자 대비 {sign}{diff}자)"
        print(f"\n✏️  수정 자소서 — {char_info}")
        print(f"   {'─'*56}")
        for line in rewrite.split("\n"):
            print(f"   {line}")
        print(f"   {'─'*56}")

    # 참고 자소서
    refs = result.get("references", [])
    if refs:
        print(f"\n{thin}")
        warn_msg = ""
        if result.get("ref_warning"):
            warn_msg = "  ⚠️  해당 기업 데이터 부족 → 유사 기업/전체 검색 사용"
        print(f"📚 참고한 합격자소서 ({len(refs)}건){warn_msg}")
        for i, r in enumerate(refs, 1):
            cc = r.get("char_count", 0)
            cc_str = f"  {cc}자" if cc else ""
            print(f"\n   [{i}] {r['company']} / {r.get('role') or '직무미상'}"
                  f"  유사도={r['similarity']:.4f}{cc_str}")
            q = r.get("question", "")
            if q:
                print(f"   Q: {q[:80]}{'…' if len(q)>80 else ''}")
            ans = r.get("answer", "")
            if ans:
                print(f"   A: {ans[:150]}{'…' if len(ans)>150 else ''}")

    # 메타
    print(f"\n{thin}")
    avg = result.get("avg_ref_chars", 0)
    avg_str = f"  |  참고평균 {avg}자" if avg else ""
    jd_str = "  |  JD ✅" if result.get("jd_used") else "  |  JD ❌"
    print(
        f"초안 {result['input_chars']}자"
        f"  →  수정본 {result.get('rewrite_chars', 0)}자"
        f"{avg_str}{jd_str}  |  토큰 {result['tokens_used']}  |  모델: {result['model']}"
    )
    print(sep + "\n")


# ── 대화형 입력 헬퍼 ──────────────────────────────────────────────────────────

def _input_multiline(prompt_text: str) -> str:
    """빈 줄 두 번 Enter 로 종료되는 여러 줄 입력"""
    print(prompt_text)
    print("(입력 완료: 빈 줄에서 Enter 두 번)")
    lines: list[str] = []
    empty_count = 0
    while empty_count < 2:
        line = input()
        if line == "":
            empty_count += 1
        else:
            empty_count = 0
            lines.append(line)
    return "\n".join(lines)


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="합격자소서 기반 자소서 첨삭 CLI",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--company",  default=None, help="지원 기업명 (예: 삼성전자)")
    parser.add_argument("--question", default=None, help="자소서 문항")
    parser.add_argument("--draft",    default=None, help="초안 텍스트")
    parser.add_argument(
        "--n_refs",  type=int,   default=3,
        help="참고 자소서 수 (기본 3)",
    )
    parser.add_argument(
        "--min_sim", type=float, default=0.5,
        help="참고 자소서 최소 유사도 (기본 0.5)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="결과를 JSON 형식으로 출력",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="데모 데이터로 실행",
    )
    args = parser.parse_args()

    # 입력 값 결정
    if args.demo:
        company  = DEMO_COMPANY
        question = DEMO_QUESTION
        draft    = DEMO_DRAFT
        print(f"\n[데모 모드]  기업: {company}")
        print(f"문항: {question[:60]}…")
    else:
        company  = args.company  or input("\n지원 기업을 입력하세요: ").strip()
        question = args.question or input("자소서 문항을 입력하세요: ").strip()
        if args.draft:
            draft = args.draft
        else:
            draft = _input_multiline("\n초안을 입력하세요:")

    if not draft.strip():
        print("오류: 초안이 비어있습니다.", file=sys.stderr)
        sys.exit(1)

    # 진행 메시지
    print(f"\n🔍 유사 자소서 검색 중... (기업: {company})")
    print("⏳ Claude 첨삭 생성 중...\n")

    # 첨삭 실행
    from ai.advisor import advise
    result = advise(
        draft=draft,
        question=question,
        company=company,
        n_refs=args.n_refs,
        min_similarity=args.min_sim,
    )

    # 출력
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_result(result)


if __name__ == "__main__":
    main()
