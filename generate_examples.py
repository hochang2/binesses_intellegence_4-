"""
기업별 자소서 예시 생성 스크립트 (GPT-4o-mini)

examples/ 폴더에 12개 기업 JSON 파일 생성
실행: python generate_examples.py
"""

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

COMPANIES = [
    {"company": "삼성전자",   "role": "소프트웨어개발자", "org_type": "corp"},
    {"company": "현대자동차", "role": "자동차SW엔지니어",  "org_type": "corp"},
    {"company": "SK하이닉스", "role": "반도체공정엔지니어","org_type": "corp"},
    {"company": "LG전자",     "role": "HW개발엔지니어",   "org_type": "corp"},
    {"company": "포스코",     "role": "생산기술엔지니어",  "org_type": "corp"},
    {"company": "한국전력",   "role": "전력계통운영",      "org_type": "public"},
    {"company": "농협은행",   "role": "IT개발직",          "org_type": "bank"},
    {"company": "기업은행",   "role": "일반행원",          "org_type": "bank"},
    {"company": "신한은행",   "role": "디지털/ICT직군",    "org_type": "bank"},
    {"company": "우리은행",   "role": "일반행원",          "org_type": "bank"},
    {"company": "국민은행",   "role": "IT직군",            "org_type": "bank"},
    {"company": "하나은행",   "role": "글로벌금융직군",    "org_type": "bank"},
]

QUESTIONS = {
    "corp":   "본인의 성장과정을 간략히 기술하되, 현재의 자신에게 가장 큰 영향을 끼친 사건이나 인물을 포함하여 기술하시기 바랍니다. (700자 내외)",
    "bank":   "지원동기와 입사 후 이루고 싶은 목표를 구체적으로 기술하시오. (600자 내외)",
    "public": "공직자로서 갖춰야 할 자세와 본인이 해당 직무에 적합한 이유를 기술하시오. (600자 내외)",
}

SYSTEM_PROMPT = """당신은 한국 대기업·금융권 합격자소서 작성 전문가입니다.
주어진 기업, 직무, 문항에 맞는 현실적인 자소서 초안을 작성하세요.

규칙:
- 실제 지원자가 쓴 것처럼 1인칭으로 작성
- 구체적인 경험과 수치 포함 (과장 아닌 현실적 수준)
- 기업 특성에 맞는 키워드 자연스럽게 포함
- 지정된 글자 수 범위 내로 작성
- JSON 형식으로만 응답: {"question": "문항", "draft": "자소서 초안"}
"""

def generate_example(client: OpenAI, info: dict) -> dict:
    company  = info["company"]
    role     = info["role"]
    org_type = info["org_type"]
    question = QUESTIONS[org_type]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                f"기업: {company}\n직무: {role}\n문항: {question}\n\n위 조건에 맞는 자소서 초안을 작성하세요."
            },
        ],
        max_tokens=1200,
    )

    parsed = json.loads(response.choices[0].message.content)
    return {
        "company":  company,
        "role":     role,
        "question": parsed.get("question", question),
        "draft":    parsed.get("draft", ""),
    }


def main():
    client  = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    out_dir = _ROOT / "examples"
    out_dir.mkdir(exist_ok=True)

    print(f"기업 예시 자소서 생성 중... ({len(COMPANIES)}개 기업)")
    print()

    for info in COMPANIES:
        company = info["company"]
        fname   = out_dir / f"{company}.json"

        if fname.exists():
            print(f"  ⏭️  {company} — 이미 존재, 스킵")
            continue

        print(f"  ⏳ {company} ({info['role']}) 생성 중...", end=" ", flush=True)
        try:
            example = generate_example(client, info)
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(example, f, ensure_ascii=False, indent=2)
            print(f"✅  ({len(example['draft'])}자)")
        except Exception as e:
            print(f"❌  오류: {e}")

    print()
    print(f"완료! examples/ 폴더에 저장됨 → {out_dir}")


if __name__ == "__main__":
    main()
