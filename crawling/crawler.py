"""
잡코리아 합격자소서 크롤러 v2
- essays.db 에 source='jobkorea' 로 저장
- 실행: python crawler.py
- 테스트(1개 기업): python crawler.py --test
"""

import sys
import io
import re
import time
import sqlite3
import logging
import argparse
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from db import DB_PATH, ORG_TYPE_MAP, init_db, already_crawled, save_essay

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 설정 ──────────────────────────────────────────────────────────────────────

REQUEST_DELAY = 1.5
BASE_URL      = "https://www.jobkorea.co.kr"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer":         "https://www.jobkorea.co.kr/starter/passassay",
}

# 수집 대상 기업 (건수 내림차순, 2026-05-21 확정 / MVP 13개)
TARGET_COMPANIES = [
    # "삼성전자",   # 248건 (이미 수집 완료)
    # "현대자동차", # 127건
    # "SK하이닉스", # 89건
    # "한국전력",   # 88건
    # "LG전자",     # 87건
    # "포스코",     # 87건
    # "농협은행",   # 56건
    # "기업은행",   # 37건
    # "신한은행",   # 32건
    # "우리은행",   # 29건
    # "국민은행",   # 29건
    "하나은행",   # 19건
]

# 부분 문자열 오매칭 방지
COMPANY_ALIASES: dict[str, list[str]] = {
    "삼성전자":   ["삼성전자"],
    "현대자동차": ["현대자동차", "현대차"],
    "SK하이닉스": ["SK하이닉스", "하이닉스"],
    "한국전력":   ["한국전력", "KEPCO"],
    "LG전자":     ["LG전자", "엘지전자", "LGE"],
    "포스코":     ["포스코", "POSCO"],
    "농협은행":   ["농협은행", "NH농협"],
    "기업은행":   ["기업은행", "IBK"],
    "신한은행":   ["신한은행"],
    "우리은행":   ["우리은행"],
    "국민은행":   ["국민은행", "KB국민"],
    "하나은행":   ["하나은행"],
}

# ── 로깅 ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("crawler_jobkorea.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── 파싱 유틸 ─────────────────────────────────────────────────────────────────

def _parse_position_info(position_info: str) -> tuple[str, str, str, str]:
    """'2023년 하반기 신입 소프트웨어개발자' → (year, season, hire_type, role)"""
    year      = re.search(r"(\d{4})년", position_info)
    season    = re.search(r"(상반기|하반기|수시|인턴)", position_info)
    hire_type = re.search(r"(신입|경력|인턴)", position_info)
    role      = re.sub(
        r"\d{4}년\s*(상반기|하반기|수시|인턴)?\s*(신입|경력|인턴)?\s*",
        "", position_info
    ).strip()
    return (
        year.group(1)      if year      else "",
        season.group(1)    if season    else "",
        hire_type.group(1) if hire_type else "",
        role,
    )


def _extract_university_major(spec_raw: str) -> tuple[str, str]:
    """
    잡코리아 spec_raw 에서 학교 등급·전공 추출.
    잡코리아는 학교명을 '서울4년', '수도권4년', '지방4년' 코드로 익명화함.
    """
    items = [x.strip() for x in spec_raw.split("|") if x.strip()]
    if not items:
        return "", ""

    university = ""
    major      = ""
    univ_idx   = -1

    # 학교 등급 or 실제 대학명 탐색
    SKIP_KW = {"학점", "토익", "오픽", "토스", "자격증", "수상", "동아리",
               "인턴", "사회활동", "봉사", "교내", "해외", "Level", "읽음"}

    for i, item in enumerate(items):
        if not university and any(
            kw in item for kw in ["4년", "2년", "대학교", "대학원", "University"]
        ):
            university = item
            univ_idx   = i
        elif not major and any(
            kw in item for kw in ["학과", "학부", "전공", "계열"]
        ):
            major = item

    # 전공 키워드 미매칭 시 학교 다음 항목 사용 (예: '영어영문학')
    if not major and univ_idx >= 0:
        next_i = univ_idx + 1
        if next_i < len(items):
            candidate = items[next_i]
            if not any(kw in candidate for kw in SKIP_KW):
                major = candidate

    return university, major


# ── HTTP 요청 ─────────────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update(HEADERS)


def fetch(url: str, params: dict | None = None, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=15)
            r.encoding = "utf-8"
            return r
        except Exception as e:
            log.warning(f"요청 실패 ({attempt+1}/{retries}): {url} — {e}")
            time.sleep(3)
    return None


# ── 크롤링 함수 ───────────────────────────────────────────────────────────────

def get_view_ids(search_term: str) -> list[int]:
    """회사명으로 전체 자소서 view_id 목록 수집"""
    view_ids: list[int] = []
    page = 1
    while True:
        r = fetch(
            f"{BASE_URL}/starter/PassAssay",
            params={"schTxt": search_term, "isFilterChecked": "0", "Page": str(page)},
        )
        if r is None:
            break

        soup  = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".question")
        if not items:
            break

        for q in items:
            a = q.find("a", href=re.compile(r"/View/(\d+)"))
            if a:
                m = re.search(r"/View/(\d+)", a["href"])
                if m:
                    view_ids.append(int(m.group(1)))

        total_m = re.search(r"총\s*([\d,]+)건", r.text)
        total   = int(total_m.group(1).replace(",", "")) if total_m else 0
        if total and len(view_ids) >= total:
            break
        if len(items) < 20:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return view_ids


def get_essay_detail(view_id: int, search_term: str) -> dict | None:
    """자소서 상세 페이지 파싱"""
    url = f"{BASE_URL}/starter/PassAssay/View/{view_id}"
    r   = fetch(url)
    if r is None:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # 회사명
    co_tag  = soup.select_one("div.viewTitWrap h2 a")
    company = co_tag.get_text(strip=True) if co_tag else search_term

    # 오매칭 검증
    aliases = COMPANY_ALIASES.get(search_term)
    if aliases and not any(alias.lower() in company.lower() for alias in aliases):
        log.info(f"  스킵(오매칭): view_id={view_id} company={company!r}")
        return None

    # 채용 구분
    em_tag                         = soup.select_one("div.viewTitWrap h2 em")
    position_info                  = em_tag.get_text(strip=True) if em_tag else ""
    year, season, hire_type, role  = _parse_position_info(position_info)

    # 스펙
    spec_raw              = " | ".join(
        li.get_text(strip=True)
        for li in soup.select("ul.specLists li")
        if "읽음" not in li.get_text()
    )
    university, major = _extract_university_major(spec_raw)

    # Q&A 파싱
    qna_pairs: list[dict] = []
    dl = soup.find("dl", class_="qnaLists")
    if dl:
        for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
            q_num_tag = dt.select_one("span.num")
            q_tx_tag  = dt.select_one("span.tx")
            a_tx_tag  = dd.select_one("div.tx")
            if a_tx_tag:
                for tag in a_tx_tag.select(".txSpllChk"):
                    tag.decompose()
            answer = a_tx_tag.get_text(separator="\n", strip=True) if a_tx_tag else ""
            qna_pairs.append({
                "q_num":    q_num_tag.get_text(strip=True) if q_num_tag else "",
                "question": q_tx_tag.get_text(strip=True)  if q_tx_tag  else "",
                "answer":   answer,
                "char_count": len(answer),
            })

    if not qna_pairs:
        return None

    return {
        "source":      "jobkorea",
        "source_id":   str(view_id),
        "company":     company,
        "search_term": search_term,
        "org_type":    ORG_TYPE_MAP.get(search_term, "corp"),
        "role":        role,
        "hire_type":   hire_type,
        "year":        year,
        "season":      season,
        "university":  university,
        "major":       major,
        "spec_raw":    spec_raw,
        "url":         url,
        "crawled_at":  datetime.now().isoformat(),
        "qna":         qna_pairs,
    }


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main(test_mode: bool = False):
    targets = TARGET_COMPANIES[:1] if test_mode else TARGET_COMPANIES
    if test_mode:
        log.info("=== 테스트 모드: 첫 번째 기업만 수집 ===")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    total_saved = total_skipped = 0

    for company in targets:
        log.info(f"{'='*50}")
        log.info(f"[{company}] view_id 목록 수집 중...")
        view_ids = get_view_ids(company)
        log.info(f"[{company}] 총 {len(view_ids)}건 발견")

        saved = skipped = failed = 0
        for i, vid in enumerate(view_ids, 1):
            if already_crawled(conn, str(vid)):
                skipped += 1
                continue

            time.sleep(REQUEST_DELAY)
            essay = get_essay_detail(vid, company)
            if essay and save_essay(conn, essay):
                saved += 1
                log.info(f"  [{i}/{len(view_ids)}] 저장: {essay['company']} / {essay['role'] or '직무미상'}")
            else:
                failed += 1
                log.warning(f"  [{i}/{len(view_ids)}] 파싱 실패 또는 중복: view_id={vid}")

        log.info(f"[{company}] 완료 — 저장:{saved} 스킵:{skipped} 실패:{failed}")
        total_saved   += saved
        total_skipped += skipped
        time.sleep(2)

    essay_cnt = conn.execute("SELECT COUNT(*) FROM essays").fetchone()[0]
    qna_cnt   = conn.execute("SELECT COUNT(*) FROM qna").fetchone()[0]
    log.info(f"\n{'='*50}")
    log.info(f"크롤링 완료!  essays={essay_cnt}행  qna={qna_cnt}행")
    log.info(f"이번 실행: 저장={total_saved}건 / 스킵={total_skipped}건")
    log.info(f"DB 경로: {DB_PATH.resolve()}")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="첫 번째 기업만 수집")
    args = parser.parse_args()
    main(test_mode=args.test)
