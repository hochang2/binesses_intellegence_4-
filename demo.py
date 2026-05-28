"""
합격자소서 RAG 첨삭 시스템 — 데모 실행기

examples/ 폴더의 기업별 예시 자소서를 골라 첨삭 결과를 출력합니다.

실행:
    python demo.py               # 기업 선택 메뉴
    python demo.py --company 삼성전자
    python demo.py --all         # 전체 기업 순서대로
    python demo.py --json        # JSON 원본 출력
"""

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EXAMPLES_DIR = _ROOT / "examples"

COMPANY_ORDER = [
    "삼성전자", "현대자동차", "SK하이닉스", "LG전자", "포스코",
    "한국전력",
    "농협은행", "기업은행", "신한은행", "우리은행", "국민은행", "하나은행",
]


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def list_examples() -> list[str]:
    """examples/ 폴더의 기업 목록 반환"""
    files = sorted(
        (f.stem for f in EXAMPLES_DIR.glob("*.json")),
        key=lambda c: COMPANY_ORDER.index(c) if c in COMPANY_ORDER else 99,
    )
    return files


def load_example(company: str) -> dict:
    path = EXAMPLES_DIR / f"{company}.json"
    if not path.exists():
        print(f"[오류] examples/{company}.json 없음 — generate_examples.py 먼저 실행하세요.",
              file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pick_company() -> str:
    companies = list_examples()
    if not companies:
        print("[오류] examples/ 폴더가 비어있습니다. generate_examples.py를 먼저 실행하세요.")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("  기업 선택")
    print("=" * 50)
    for i, c in enumerate(companies, 1):
        print(f"  {i:2d}. {c}")
    print("=" * 50)

    while True:
        try:
            choice = input("번호 입력 (Enter = 1번): ").strip() or "1"
            idx = int(choice) - 1
            if 0 <= idx < len(companies):
                return companies[idx]
        except (ValueError, KeyboardInterrupt):
            pass
        print("  다시 입력하세요.")


def run_one(company: str, json_mode: bool = False) -> None:
    example = load_example(company)

    print(f"\n🏢  기업: {example['company']}  |  직무: {example['role']}")
    print(f"📋  문항: {example['question'][:60]}{'…' if len(example['question']) > 60 else ''}")
    print(f"📝  초안 미리보기: {example['draft'][:80]}…")
    print("\n🔍 유사 자소서 검색 중...")
    print("⏳ GPT 첨삭 생성 중...\n")

    from ai.advisor import advise
    result = advise(
        draft=example["draft"],
        question=example["question"],
        company=example["company"],
    )

    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # ── 보기 좋게 출력 ────────────────────────────────────────────────────────
    sep  = "=" * 62
    thin = "─" * 62

    print(f"\n{sep}")
    print(f"  📋 첨삭 결과 — {result['company']}")
    print(sep)

    # 원본
    print(f"\n📄 원본 초안 ({result['input_chars']}자)")
    print(f"   {thin[:56]}")
    for line in result["draft"].split("\n"):
        print(f"   {line}")
    print(f"   {thin[:56]}")

    # 총평
    print(f"\n📝 총평\n   {result['summary']}")

    # 잘된 점
    print(f"\n✅ 잘된 점")
    for i, p in enumerate(result.get("pros", []), 1):
        print(f"   {i}. {p}")

    # 개선 필요
    print(f"\n⚠️  개선 필요")
    for i, c in enumerate(result.get("cons", []), 1):
        if isinstance(c, dict):
            print(f"   {i}. [{c.get('point','')}]")
            print(f"      이유: {c.get('reason','')}")
            print(f"      제안: {c.get('suggestion','')}")
        else:
            print(f"   {i}. {c}")

    # 수정 자소서
    rewrite = result.get("rewrite", "")
    if rewrite:
        import re as _re
        rewrite = _re.sub(r"<br\s*/?>", "\n", rewrite, flags=_re.IGNORECASE)
        rewrite = _re.sub(r"<[^>]+>", "", rewrite)
        rlen = len(rewrite)
        avg  = result.get("avg_ref_chars", 0)
        diff = rlen - avg
        sign = "+" if diff >= 0 else ""
        info = f"{rlen}자"
        if avg:
            info += f"  (참고평균 {avg}자 대비 {sign}{diff}자)"
        print(f"\n✏️  수정 자소서 — {info}")
        print(f"   {thin[:56]}")
        for line in rewrite.split("\n"):
            print(f"   {line}")
        print(f"   {thin[:56]}")

    # 참고 자소서
    refs = result.get("references", [])
    if refs:
        warn = "  ⚠️  유사기업/전체 검색 사용" if result.get("ref_warning") else ""
        print(f"\n{thin}")
        print(f"📚 참고 합격자소서 ({len(refs)}건){warn}")
        for i, r in enumerate(refs, 1):
            cc = r.get("char_count", 0)
            print(f"\n   [{i}] {r['company']} / {r.get('role') or '직무미상'}"
                  f"  유사도={r['similarity']:.4f}"
                  + (f"  {cc}자" if cc else ""))
            if r.get("question"):
                print(f"   Q: {r['question'][:80]}{'…' if len(r['question'])>80 else ''}")
            if r.get("answer"):
                print(f"   A: {r['answer'][:120]}…")

    # 메타
    avg_str = f"  |  참고평균 {result.get('avg_ref_chars',0)}자" if result.get("avg_ref_chars") else ""
    jd_str  = "  |  JD ✅" if result.get("jd_used") else "  |  JD ❌"
    print(f"\n{thin}")
    print(f"초안 {result['input_chars']}자  →  수정본 {result.get('rewrite_chars',0)}자"
          f"{avg_str}{jd_str}  |  토큰 {result['tokens_used']}  |  {result['model']}")
    print(sep + "\n")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="합격자소서 RAG 첨삭 데모")
    parser.add_argument("--company", default=None, help="기업명 (예: 삼성전자)")
    parser.add_argument("--all",  action="store_true", help="전체 기업 순서대로 실행")
    parser.add_argument("--json", action="store_true", help="JSON 원본 출력")
    parser.add_argument("--list", action="store_true", help="기업 목록만 출력")
    args = parser.parse_args()

    if args.list:
        for c in list_examples():
            print(c)
        return

    if args.all:
        for company in list_examples():
            run_one(company, args.json)
        return

    company = args.company or pick_company()
    run_one(company, args.json)


if __name__ == "__main__":
    main()
