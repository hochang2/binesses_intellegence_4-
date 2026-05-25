"""
자소서 첨삭 메인 모듈 (OpenAI GPT 버전)

흐름:
  1. 3단계 fallback RAG 검색 (기업 → org_type → 전체)
  2. 프롬프트 구성 (prompt.py)
  3. OpenAI Chat Completions API 호출
  4. JSON 파싱 + 최대 2회 재시도
  5. 결과 dict 반환

사용:
    from advisor import advise
    result = advise(draft="...", question="...", company="삼성전자")
"""

import json
import os
import re

import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from openai import OpenAI

from crawling.db import ORG_TYPE_MAP
from ai.search   import retrieve
from ai.prompt   import SYSTEM_PROMPT, build_user_prompt
from ai.jd_data  import get_jd_summary

# .env 로드
load_dotenv()

# ── 상수 ─────────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "gpt-4o-mini"   # 비용 효율적, Haiku 수준 빠른 응답
MAX_RETRIES   = 2               # JSON 파싱 실패 시 재시도 횟수
MAX_TOKENS    = 3000            # 출력 토큰 한도 (전체 수정 자소서 포함)


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _search_with_fallback(
    query: str,
    company: str,
    n_refs: int,
    min_similarity: float,
) -> tuple[list[dict], bool]:
    """
    3단계 fallback RAG 검색.

    1단계: 기업(company) 필터
    2단계: 업종(org_type) 필터  → 기업 데이터 부족 시
    3단계: 필터 없음 (전체)    → org_type 도 없거나 결과 없을 때

    Returns
    -------
    (results, ref_warning)
      ref_warning=True  → 해당 기업 데이터 없어 fallback 사용
    """
    # 1단계: 기업 필터
    results = retrieve(query, company=company, n_results=n_refs)
    results = [r for r in results if r["similarity"] >= min_similarity]
    if results:
        return results, False

    # 2단계: org_type 필터
    org_type = ORG_TYPE_MAP.get(company)
    if org_type:
        results = retrieve(query, org_type=org_type, n_results=n_refs)
        results = [r for r in results if r["similarity"] >= min_similarity]
        if results:
            return results, True

    # 3단계: 전체 검색
    results = retrieve(query, n_results=n_refs)
    results = [r for r in results if r["similarity"] >= min_similarity]
    return results, True


def _extract_json(text: str) -> dict:
    """
    응답 텍스트에서 JSON 파싱.
    ```json ... ``` 코드블록 래핑도 처리.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text.strip())


# ── 메인 함수 ─────────────────────────────────────────────────────────────────

def advise(
    draft: str,
    question: str,
    company: str,
    *,
    n_refs: int           = 3,
    min_similarity: float = 0.5,
    model: str            = DEFAULT_MODEL,
) -> dict:
    """
    자소서 첨삭 메인 함수.

    Parameters
    ----------
    draft          : 사용자 자소서 초안
    question       : 자소서 문항 (문자열)
    company        : 지원 기업명 (예: '삼성전자')
    n_refs         : 참고 자소서 수 (기본 3)
    min_similarity : 참고로 사용할 최소 유사도 (기본 0.5)
    model          : OpenAI 모델 ID (기본 gpt-4o-mini)

    Returns
    -------
    dict:
        summary      (str)       전체 총평
        pros         (list[str]) 잘된 점
        cons         (list[dict]) 개선점 [{point, reason, suggestion}]
        rewrite      (str)       핵심 문장 수정 제안
        references   (list[dict]) 참고한 합격자소서 [{company, role, question, answer, similarity}]
        ref_warning  (bool)      True = 해당 기업 데이터 없어 fallback 검색 사용
        input_chars  (int)       사용자 초안 글자 수
        tokens_used  (int)       API 사용 토큰 합계
        model        (str)       사용된 모델 ID
    """
    # ── 1. RAG 검색 ──────────────────────────────────────────────────────────
    query = f"{question}\n{draft}"
    refs, ref_warning = _search_with_fallback(
        query=query,
        company=company,
        n_refs=n_refs,
        min_similarity=min_similarity,
    )

    # ── 2. 참고자소서 평균 글자수 계산 ───────────────────────────────────────
    char_counts = [r.get("char_count", 0) for r in refs if r.get("char_count", 0) > 0]
    avg_ref_chars = int(sum(char_counts) / len(char_counts)) if char_counts else 0

    # ── 3. 프롬프트 구성 ──────────────────────────────────────────────────────
    jd_summary = get_jd_summary(company)
    user_prompt = build_user_prompt(
        draft=draft,
        question=question,
        company=company,
        references=refs,
        avg_ref_chars=avg_ref_chars,
        jd_summary=jd_summary,
    )

    # ── 4. OpenAI API 호출 (retry 포함) ──────────────────────────────────────
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    parsed: dict = {}
    tokens_used  = 0

    for attempt in range(MAX_RETRIES + 1):
        suffix = "\n\n반드시 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요." if attempt > 0 else ""

        response = client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},   # JSON mode 강제
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt + suffix},
            ],
        )

        raw_text    = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0

        try:
            parsed = _extract_json(raw_text)
            break  # 성공
        except (json.JSONDecodeError, ValueError):
            if attempt < MAX_RETRIES:
                continue
            # 최종 파싱 실패: summary 에 원문 담아 반환
            parsed = {
                "summary":  raw_text[:500],
                "pros":     [],
                "cons":     [],
                "rewrite":  "",
                "_raw":     raw_text,
            }

    # ── 5. 결과 조합 ──────────────────────────────────────────────────────────
    rewrite_text = parsed.get("rewrite", "")
    return {
        "draft":         draft,                      # 원본 초안
        "summary":       parsed.get("summary", ""),
        "pros":          parsed.get("pros", []),
        "cons":          parsed.get("cons", []),
        "rewrite":       rewrite_text,
        "input_chars":   len(draft),
        "rewrite_chars": len(rewrite_text),
        "avg_ref_chars": avg_ref_chars,              # 참고자소서 평균 글자수
        "references":  [
            {
                "company":    r["company"],
                "role":       r.get("role", ""),
                "question":   r.get("question", ""),
                "answer":     (r.get("answer") or "")[:300],
                "similarity": r["similarity"],
                "char_count": r.get("char_count", 0),
            }
            for r in refs
        ],
        "ref_warning":   ref_warning,
        "jd_used":       bool(jd_summary),
        "tokens_used":   tokens_used,
        "model":         model,
    }
