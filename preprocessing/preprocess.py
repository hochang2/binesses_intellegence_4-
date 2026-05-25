"""
합격자소서 전처리 파이프라인
1. 텍스트 정제 (clean_text)
2. 링커리어 Q&A 분리 (split_linkareer_qna) — __RAW__ 마커 행 처리
3. 최소 길이 필터 (is_valid = 0)
4. 질문 유형 분류 (classify_question_type)
5. 패턴② 재분리 (fix_split_pattern2) — 기존 분리 실패 중 질문문장 패턴

실행:
  python preprocess.py           # DB 전처리 실행
  python preprocess.py --dry-run # 샘플 테스트만 (DB 수정 없음)
"""

import re
import sys
import io
import sqlite3
import argparse
import logging
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가 (crawling.db import 용)
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from crawling.db import DB_PATH

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── 설정 ──────────────────────────────────────────────────────────────────────

MIN_ANSWER_LEN = 50   # 이보다 짧은 답변은 is_valid = 0

# ── 패턴 1: 표준 구분자 (Q1 / 1. / 【】 / [] / ■◆)
QA_SPLIT_RE = re.compile(
    r'(?:^|\n)\s*'
    r'(?:'
    r'Q\.?\s*\d+'                        # Q1  Q.1  Q 1
    r'|【[^】]{1,30}】'                  # 【성장과정】
    r'|\[[^\]]{1,30}\]'                  # [성장과정]
    r'|\d+\s*[\.、．)）]\s*(?=[가-힣])'  # 1. / 1) 뒤에 한글
    r'|[■◆▶◎●]\s*(?=[가-힣])'          # ■ ◆ ▶ 뒤에 한글
    r')',
    re.MULTILINE,
)

# ── 패턴 2: 번호 없이 질문문장(~하십시오/~하세요)으로 바로 시작하는 포맷
#   예) "삼성전자를 지원한 이유와 입사 후 꿈을 기술하십시오. - 갤럭시 생태계\n[답변]"
#   오매칭 방지: 키워드 이후 짧은 부가텍스트(마침표·자수표기·소제목)만 허용
QA_QUESTION_RE = re.compile(
    r'(?:^|\n)'
    r'(?='
    r'[가-힣(「].{5,200}?'               # 한글로 시작, 내용 5~200자 (비탐욕)
    r'(?:기술하십시오|작성하십시오|서술하십시오|설명하십시오'
    r'|기술해\s*주십시오|작성해\s*주십시오|말씀해\s*주십시오'
    r'|기술하세요|작성하세요|바랍니다)'
    r'[.!?]?'                            # 선택적 문장부호
    r'(?:\s*\([^\n]{0,30}\))?'           # 선택적 (700자 이내) 표기
    r'(?:\s*[-–]\s*[^\n]{0,40})?'        # 선택적 - 소제목
    r'\s*\n'                             # 반드시 줄바꿈으로 마무리
    r')',
    re.MULTILINE,
)

# 질문 유형 키워드 (우선순위 순)
QUESTION_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("growth",      ["성장과정", "성장 과정", "어린 시절", "학창 시절", "유년", "성장 배경"]),
    ("motivation",  ["지원 동기", "지원동기", "지원하게 된", "왜 지원", "관심을 갖게", "지원한 이유"]),
    ("experience",  ["경험", "활동", "프로젝트", "인턴", "아르바이트", "도전", "실패", "성취"]),
    ("fit",         ["직무", "역량", "강점", "포부", "비전", "기여", "발휘"]),
    ("personality", ["성격", "장단점", "단점", "장점", "성향", "특기"]),
    ("goal",        ["입사 후", "목표", "10년", "5년", "커리어", "미래"]),
]


# ── 순수 함수 (DB 의존 없음) ──────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """HTML 엔티티·전각공백·빈줄·도입부 홍보문구 정제"""
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#39;", "'")
    text = text.replace("　", " ")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(
        r"^[^\n]{0,10}(안녕하세요|지원하게\s*된|귀사에\s*지원|처음\s*뵙겠습니다)[^\n]*\n?",
        "", text, count=1,
    )
    return text.strip()


def _build_pairs(content: str, splits: list) -> list[dict]:
    """매칭된 splits 위치로 Q&A 쌍 구성 (공통 로직)"""
    pairs = []
    for i, m in enumerate(splits):
        block_start = m.start()
        block_end   = splits[i + 1].start() if i + 1 < len(splits) else len(content)
        block       = content[block_start:block_end].strip()

        lines    = block.split("\n", 1)
        question = lines[0].strip()
        answer   = lines[1].strip() if len(lines) > 1 else ""

        if not answer:
            continue
        pairs.append({"q_num": f"Q{i+1}", "question": question, "answer": answer})
    return pairs


def split_linkareer_qna(content: str) -> list[dict]:
    """
    링커리어 content를 Q&A 쌍으로 분리.

    시도 순서:
      1차) QA_SPLIT_RE  — Q1 / 1. / 【】 / [] / ■ 등 표준 구분자
      2차) QA_QUESTION_RE — '~하십시오.' 로 끝나는 질문문장 직접 인식
      실패) 전체를 answer 1개로 반환
    """
    # 1차: 표준 구분자
    splits = list(QA_SPLIT_RE.finditer(content))
    if splits:
        pairs = _build_pairs(content, splits)
        if pairs:
            return pairs

    # 2차: 질문문장 패턴
    splits = list(QA_QUESTION_RE.finditer(content))
    if splits:
        pairs = _build_pairs(content, splits)
        if pairs:
            return pairs

    # 분리 불가 — 전체를 하나로
    return [{"q_num": "", "question": "", "answer": content.strip()}]


def classify_question_type(question: str, answer: str = "") -> str:
    """질문 + 답변 앞 200자로 유형 분류"""
    combined = question + " " + answer[:200]
    for qtype, keywords in QUESTION_TYPE_RULES:
        if any(kw in combined for kw in keywords):
            return qtype
    return "etc"


# ── DB 처리 함수 ──────────────────────────────────────────────────────────────

def process_linkareer_raw(conn: sqlite3.Connection) -> int:
    """question='__RAW__' 임시 행 → Q&A 분리 후 교체"""
    raw_rows = conn.execute(
        "SELECT id, essay_id, answer FROM qna WHERE question = '__RAW__'"
    ).fetchall()

    processed = 0
    for raw_id, essay_id, content in raw_rows:
        pairs = split_linkareer_qna(clean_text(content))
        conn.execute("DELETE FROM qna WHERE id = ?", (raw_id,))
        conn.executemany(
            """INSERT INTO qna
               (essay_id, q_num, question, answer_clean, answer, char_count, is_valid)
               VALUES (?,?,?,?,?,?,?)""",
            [
                (
                    essay_id, p["q_num"], p["question"],
                    p["answer"], p["answer"],
                    len(p["answer"]),
                    1 if len(p["answer"]) >= MIN_ANSWER_LEN else 0,
                )
                for p in pairs
            ],
        )
        processed += 1

    conn.commit()
    return processed


def fix_split_pattern2(conn: sqlite3.Connection) -> int:
    """
    링커리어 분리 실패(1개짜리) 중 QA_QUESTION_RE로 재분리 가능한 건 재처리.
    이미 처리된 경우 재실행해도 안전 (question='' 조건으로 필터링).
    Returns: 재분리 성공한 essay 수
    """
    # 분리 실패 = 유효 qna 1개 + question 이 빈값인 링커리어 essay
    singles = conn.execute("""
        SELECT e.id AS essay_id, q.id AS qna_id, q.answer AS content
        FROM essays e JOIN qna q ON q.essay_id = e.id
        WHERE e.source = 'linkareer'
          AND q.is_valid = 1
          AND (q.question = '' OR q.question IS NULL)
        GROUP BY e.id
        HAVING COUNT(q.id) = 1
    """).fetchall()

    fixed = 0
    for essay_id, qna_id, content in singles:
        if not content:
            continue

        pairs = split_linkareer_qna(content)
        if len(pairs) < 2:
            continue   # 여전히 분리 불가 → 스킵

        # 기존 단일 행 삭제
        conn.execute("DELETE FROM qna WHERE id = ?", (qna_id,))

        # 새 분리 행 삽입 (question_clean / answer_clean / question_type 즉시 채움)
        for i, p in enumerate(pairs, 1):
            a_clean = clean_text(p["answer"])
            q_clean = clean_text(p["question"])
            qtype   = classify_question_type(q_clean, a_clean)
            valid   = 1 if len(a_clean) >= MIN_ANSWER_LEN else 0
            conn.execute(
                """INSERT INTO qna
                   (essay_id, q_num, question, answer, question_clean, answer_clean,
                    question_type, char_count, is_valid)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (essay_id, f"Q{i}", p["question"], p["answer"],
                 q_clean, a_clean, qtype, len(a_clean), valid),
            )
        conn.commit()
        fixed += 1

    return fixed


def process_clean_and_classify(conn: sqlite3.Connection) -> int:
    """question_clean 이 NULL 인 행에 clean_text + 유형 분류 적용"""
    rows = conn.execute(
        """SELECT id, question, answer FROM qna
           WHERE question_clean IS NULL
             AND question != '__RAW__'
             AND is_valid = 1"""
    ).fetchall()

    updated = 0
    for row_id, question, answer in rows:
        q_clean  = clean_text(question or "")
        a_clean  = clean_text(answer   or "")
        qtype    = classify_question_type(q_clean, a_clean)
        is_valid = 1 if len(a_clean) >= MIN_ANSWER_LEN else 0
        conn.execute(
            """UPDATE qna
               SET question_clean=?, answer_clean=?, question_type=?, is_valid=?
               WHERE id=?""",
            (q_clean, a_clean, qtype, is_valid, row_id),
        )
        updated += 1

    conn.commit()
    return updated


def run_all(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)

    log.info("[ 1/3 ] 링커리어 Q&A 분리 중...")
    n1 = process_linkareer_raw(conn)
    log.info(f"        → {n1}개 essay 처리 완료")

    log.info("[ 2/3 ] 텍스트 정제 + 유형 분류 중...")
    n2 = process_clean_and_classify(conn)
    log.info(f"        → {n2}개 qna 행 업데이트 완료")

    log.info("[ 3/3 ] 패턴② 재분리 중 (질문문장 패턴)...")
    n3 = fix_split_pattern2(conn)
    log.info(f"        → {n3}개 essay 재분리 완료")

    stats = conn.execute(
        """SELECT question_type, COUNT(*) FROM qna
           WHERE is_valid=1 AND question_type IS NOT NULL
           GROUP BY question_type ORDER BY 2 DESC"""
    ).fetchall()
    log.info("\n유형 분류 분포:")
    for qtype, cnt in stats:
        log.info(f"  {qtype:12s}: {cnt}건")

    conn.close()


# ── 드라이런 테스트 ───────────────────────────────────────────────────────────

def run_dry_run() -> None:
    print("=" * 60)
    print("[ DRY RUN ] 전처리 함수 단위 테스트")
    print("=" * 60)

    # clean_text 테스트
    cases_clean = [
        ("안녕하세요, SK하이닉스에 지원한 홍길동입니다.\n\n저는 어릴 때부터...",
         "저는 어릴 때부터...", "도입부 제거"),
        ("경험\n\n\n\n\n내용입니다.", "경험\n\n내용입니다.", "연속 빈줄 압축"),
        ("&amp;amp; &lt;br&gt; 　전각공백",
         "&amp; <br> 　전각공백".replace("　", " "), "HTML엔티티+전각공백"),
    ]
    print("\n▶ clean_text()")
    for raw, expected, label in cases_clean:
        result = clean_text(raw)
        ok = "✓" if expected in result or result == expected.strip() else "✗"
        print(f"  [{ok}] {label}")
        if ok == "✗":
            print(f"      기대: {expected!r}")
            print(f"      결과: {result!r}")

    # split_linkareer_qna 테스트 — 표준 패턴
    sample_std = """
1. 성장과정
저는 경남 시골에서 태어나 부모님의 손에서 성장했습니다.

2. 지원동기
SK하이닉스가 세계 반도체 시장에서 차지하는 위치에 매료되어...
"""
    print("\n▶ split_linkareer_qna() — 표준 구분자(1.)")
    for p in split_linkareer_qna(sample_std):
        print(f"  Q: {p['question'][:50]!r}")
        print(f"  A: {p['answer'][:60]!r}\n")

    # split_linkareer_qna 테스트 — 패턴②
    sample_q = """삼성전자를 지원한 이유와 입사 후 회사에서 이루고 싶은 꿈을 기술하십시오.
삼성전자의 반도체 기술력과 글로벌 시장 지위에 매료되어 지원하였습니다.
반도체 미세공정 한계를 극복하는 연구에 기여하고 싶습니다.

본인의 성장과정을 간략히 기술하되 현재의 자신에게 가장 큰 영향을 끼친 사건, 인물 등을 기술하십시오.
고등학교 시절 아버지의 사업 실패를 겪으며 경제적 자립의 중요성을 배웠습니다.
그 경험이 저를 더욱 단단하게 만들었습니다.
"""
    print("▶ split_linkareer_qna() — 패턴②(질문문장 직접)")
    pairs = split_linkareer_qna(sample_q)
    print(f"  분리 수: {len(pairs)}개 (기대: 2개) {'✓' if len(pairs)==2 else '✗'}")
    for p in pairs:
        print(f"  Q: {p['question'][:60]!r}")
        print(f"  A: {p['answer'][:60]!r}\n")

    # classify_question_type 테스트
    cases_qtype = [
        ("성장과정", "growth"),
        ("지원 동기를 기술하시오.", "motivation"),
        ("자신의 경험을 바탕으로 설명하시오.", "experience"),
        ("입사 후 5년 계획을 서술하시오.", "goal"),
        ("성격의 장단점을 기술하시오.", "personality"),
        ("직무 역량 및 강점을 서술하시오.", "fit"),
        ("우리 회사에 대해 아는 것.", "etc"),
    ]
    print("▶ classify_question_type()")
    all_ok = True
    for question, expected in cases_qtype:
        result = classify_question_type(question)
        ok = "✓" if result == expected else "✗"
        if ok == "✗":
            all_ok = False
        print(f"  [{ok}] {question[:30]!r:35s} → {result} (기대: {expected})")

    print("\n" + "=" * 60)
    print("DRY RUN 완료" + ("  — 모든 케이스 통과" if all_ok else "  — 일부 케이스 실패"))
    print("=" * 60)


# ── 엔트리포인트 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="DB 수정 없이 함수 단위 테스트만 실행")
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run()
    else:
        if not DB_PATH.exists():
            print(f"DB 파일 없음: {DB_PATH}\n크롤러를 먼저 실행하세요.")
            sys.exit(1)
        run_all()
