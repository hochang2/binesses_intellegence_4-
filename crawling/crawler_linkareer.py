"""
링커리어 합격자소서 GraphQL 크롤러
- essays.db 에 source='linkareer' 로 저장
- content 는 Q&A 미분리 상태로 저장 → preprocess.py 에서 분리
- 실행 (전체): python crawler_linkareer.py
- 실행 (테스트): python crawler_linkareer.py --test
"""

import sys
import io
import time
import sqlite3
import logging
import argparse
import requests
from datetime import datetime

from db import DB_PATH, ORG_TYPE_MAP, init_db, already_crawled, save_essay

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 설정 ──────────────────────────────────────────────────────────────────────

REQUEST_DELAY = 1.5
PAGE_SIZE     = 50
GRAPHQL_URL   = "https://api.linkareer.com/graphql"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":  "application/json",
    "Origin":  "https://linkareer.com",
    "Referer": "https://linkareer.com/",
}

TARGET_COMPANIES = [
    "삼성전자", "현대자동차", "SK하이닉스", "한국전력", "LG전자",
    "포스코", "농협은행", "기업은행", "신한은행",
    "우리은행", "국민은행", "하나은행",
]

# 링커리어 types 필드 매핑
# MAJOR_COMPANY / SME / PUBLIC_INSTITUTION 은 기업규모 필터 → 고용형태 아님
HIRE_TYPE_MAP = {
    "NEWCOMER": "신입",
    "INTERN":   "인턴",
    "CAREER":   "경력",
}

# ── 로깅 ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crawler_linkareer.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── GraphQL 쿼리 빌더 ─────────────────────────────────────────────────────────

def _make_query(company: str, page: int) -> str:
    """
    변수 인라인 방식 (Int! 타입 오류 방지).
    organizationName 은 쌍따옴표 이스케이프 처리.
    """
    safe_company = company.replace('"', '\\"')
    return (
        'query { coverLetters('
        f'filterBy: {{ status: PUBLISHED, organizationName: "{safe_company}" }}, '
        f'pagination: {{ page: {page}, pageSize: {PAGE_SIZE} }}, '
        'orderBy: { field: PASSED_AT, direction: DESC }'
        ') { totalCount edges { node { id organizationName role university major types content } } } }'
    )


# ── HTTP 요청 ─────────────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update(HEADERS)


def fetch_page(company: str, page: int, retries: int = 3) -> dict | None:
    """GraphQL 한 페이지 요청 → {'totalCount': N, 'list': [...]} 반환"""
    query = _make_query(company, page)
    for attempt in range(retries):
        try:
            r = session.post(GRAPHQL_URL, json={"query": query}, timeout=20)
            r.raise_for_status()
            body = r.json()
            if "errors" in body:
                log.warning(f"GraphQL 오류 (page={page}): {body['errors']}")
                return None
            return body["data"]["coverLetters"]
        except Exception as e:
            log.warning(f"요청 실패 ({attempt+1}/{retries}): {e}")
            time.sleep(3)
    return None


# ── 크롤링 함수 ───────────────────────────────────────────────────────────────

def crawl_company(
    conn: sqlite3.Connection,
    company: str,
    max_items: int | None = None,
) -> tuple[int, int, int]:
    """
    한 기업의 합격자소서를 수집하여 DB에 저장.
    Returns: (saved, skipped, failed)
    """
    saved = skipped = failed = 0
    page  = 1

    while True:
        result = fetch_page(company, page)
        if result is None:
            break

        total = result.get("totalCount", 0)
        edges = result.get("edges", [])
        items = [e["node"] for e in edges if e.get("node")]
        if not items:
            break

        for item in items:
            source_id = f"lr_{item['id']}"   # 잡코리아 view_id 와 충돌 방지

            if already_crawled(conn, source_id):
                skipped += 1
                continue

            content = (item.get("content") or "").strip()
            if not content:
                failed += 1
                continue

            types_raw  = item.get("types") or []
            # 고용형태만 추출 (MAJOR_COMPANY 등 기업규모 코드 제외)
            hire_types = [HIRE_TYPE_MAP[t] for t in types_raw if t in HIRE_TYPE_MAP]
            hire_type  = "/".join(hire_types) if hire_types else ""

            essay = {
                "source":      "linkareer",
                "source_id":   source_id,
                "company":     item.get("organizationName") or company,
                "search_term": company,
                "org_type":    ORG_TYPE_MAP.get(company, "corp"),
                "role":        item.get("role") or "",
                "hire_type":   hire_type,
                "year":        "",   # 링커리어는 연도 미제공
                "season":      "",
                "university":  item.get("university") or "",
                "major":       item.get("major") or "",
                "spec_raw": " | ".join(filter(None, [
                    item.get("university", ""),
                    item.get("major", ""),
                    hire_type,
                ])),
                "url":        f"https://linkareer.com/cover-letter/{item['id']}",
                "crawled_at": datetime.now().isoformat(),

                # content 를 단일 qna 로 임시 저장
                # question = "__RAW__" 마커로 preprocess.py 가 분리 대상 식별
                "qna": [{
                    "q_num":    "",
                    "question": "__RAW__",
                    "answer":   content,
                    "char_count": len(content),
                }],
            }
            if save_essay(conn, essay):
                saved += 1
            else:
                skipped += 1

        collected = saved + skipped + failed
        log.info(
            f"  [{company}] page={page} +{len(items)}건 "
            f"(저장:{saved} 스킵:{skipped} 실패:{failed} / 총 {total}건)"
        )

        if max_items and collected >= max_items:
            break
        if len(items) < PAGE_SIZE or collected >= total:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    return saved, skipped, failed


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main(test_mode: bool = False):
    targets   = TARGET_COMPANIES[:1] if test_mode else TARGET_COMPANIES
    max_items = 20 if test_mode else None   # 테스트 시 기업당 20건만

    if test_mode:
        log.info("=== 테스트 모드: 첫 번째 기업 최대 20건 ===")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    total_saved = total_skipped = 0
    for company in targets:
        log.info(f"{'='*50}")
        log.info(f"[링커리어/{company}] 수집 시작")
        s, sk, f = crawl_company(conn, company, max_items=max_items)
        log.info(f"[링커리어/{company}] 완료 — 저장:{s} 스킵:{sk} 실패:{f}")
        total_saved   += s
        total_skipped += sk
        time.sleep(2)

    essay_cnt = conn.execute("SELECT COUNT(*) FROM essays").fetchone()[0]
    qna_cnt   = conn.execute("SELECT COUNT(*) FROM qna").fetchone()[0]
    log.info(f"\n{'='*50}")
    log.info(f"링커리어 크롤링 완료!  essays={essay_cnt}행  qna={qna_cnt}행")
    log.info(f"이번 실행: 저장={total_saved}건 / 스킵={total_skipped}건")
    log.info(f"DB 경로: {DB_PATH.resolve()}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="첫 번째 기업 20건만 수집")
    args = parser.parse_args()
    main(test_mode=args.test)
