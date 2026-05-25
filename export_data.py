"""
데이터 내보내기 스크립트

essays.db (SQLite) + chroma_db (ChromaDB) → CSV

생성 파일:
  data/essays.csv          - 자소서 메타데이터
  data/qna.csv             - Q&A 쌍 + 기업 정보 (join)
  data/chroma_docs.csv     - ChromaDB 저장 문서 + 메타데이터 (벡터 제외)

사용:
    python export_data.py              # data/ 폴더에 CSV 생성
    python export_data.py --no-chroma  # essays.db만 내보내기
    python export_data.py --out mydir  # 출력 디렉터리 지정
"""

import csv
import sys
import sqlite3
import argparse
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from crawling.db import DB_PATH

CHROMA_PATH = str(_ROOT / "chroma_db")
COLLECTION  = "cover_letters"

# ── 컬럼 정의 ─────────────────────────────────────────────────────────────────

ESSAYS_COLS = [
    "id", "source", "source_id",
    "company", "search_term", "org_type",
    "role", "hire_type", "year", "season",
    "university", "major",
    "url", "crawled_at",
]

QNA_JOIN_HEADERS = [
    "id", "essay_id",
    "q_num", "question", "answer",
    "question_clean", "answer_clean", "question_type",
    "char_count", "is_valid",
    "source", "company", "org_type",
    "role", "year", "season",
]

CHROMA_HEADERS = [
    "chroma_id", "company", "org_type", "role",
    "question_type", "year", "season",
    "char_count", "qna_id", "essay_id", "source",
    "document_text",
]


# ── DB 내보내기 ───────────────────────────────────────────────────────────────

def export_sqlite(db_path: Path, out_dir: Path) -> dict:
    """essays.db → essays.csv, qna.csv"""
    if not db_path.exists():
        print(f"[오류] DB 파일 없음: {db_path}", file=sys.stderr)
        return {}

    conn = sqlite3.connect(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}

    # essays.csv
    rows = conn.execute(
        f"SELECT {', '.join(ESSAYS_COLS)} FROM essays ORDER BY id"
    ).fetchall()
    with open(out_dir / "essays.csv", "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows([ESSAYS_COLS] + list(rows))
    counts["essays"] = len(rows)

    # qna.csv (essays join 포함)
    rows = conn.execute("""
        SELECT q.id, q.essay_id,
               q.q_num, q.question, q.answer,
               q.question_clean, q.answer_clean, q.question_type,
               q.char_count, q.is_valid,
               e.source, e.company, e.org_type,
               e.role, e.year, e.season
        FROM qna q
        JOIN essays e ON e.id = q.essay_id
        ORDER BY q.id
    """).fetchall()
    with open(out_dir / "qna.csv", "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows([QNA_JOIN_HEADERS] + list(rows))
    counts["qna"] = len(rows)

    conn.close()
    return counts


# ── ChromaDB 내보내기 (chroma.sqlite3 직접 읽기) ──────────────────────────────

def export_chroma(out_dir: Path) -> int:
    """
    chroma_db/chroma.sqlite3 직접 읽기 → chroma_docs.csv
    (HNSW 바이너리 인덱스 우회 — 벡터 제외, 문서 텍스트 + 메타데이터만)
    """
    sqlite_path = Path(CHROMA_PATH) / "chroma.sqlite3"
    if not sqlite_path.exists():
        print(f"[오류] chroma.sqlite3 없음: {sqlite_path}", file=sys.stderr)
        return 0

    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(sqlite_path)

    # ① 전체 embedding id 목록 조회
    emb_rows = conn.execute(
        "SELECT id, embedding_id FROM embeddings ORDER BY id"
    ).fetchall()
    total = len(emb_rows)
    print(f"  ChromaDB: {total:,}건 조회 중...")

    # ② 전체 메타데이터를 한번에 읽어 Python dict로 피벗
    meta_rows = conn.execute(
        "SELECT id, key, string_value, int_value FROM embedding_metadata"
    ).fetchall()
    conn.close()

    # embedding id → {key: value} 딕셔너리
    meta_map: dict[int, dict] = {}
    for emb_id, key, sv, iv in meta_rows:
        if emb_id not in meta_map:
            meta_map[emb_id] = {}
        # string_value 우선, 없으면 int_value
        meta_map[emb_id][key] = sv if sv is not None else iv

    # ③ 행 조립
    rows = []
    for emb_id, embedding_id in emb_rows:
        m = meta_map.get(emb_id, {})
        rows.append([
            embedding_id,                      # chroma_id (예: qna_100)
            m.get("company", ""),
            m.get("org_type", ""),
            m.get("role", ""),
            m.get("question_type", ""),
            m.get("year", ""),
            m.get("season", ""),
            m.get("char_count", 0),
            m.get("qna_id", 0),
            m.get("essay_id", 0),
            m.get("source", ""),
            m.get("chroma:document", ""),      # 문서 텍스트
        ])

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "chroma_docs.csv", "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows([CHROMA_HEADERS] + rows)

    return len(rows)


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="essays.db + ChromaDB → CSV 내보내기")
    parser.add_argument("--out",       default="data",      help="출력 디렉터리 (기본: data/)")
    parser.add_argument("--db",        default=str(DB_PATH), help="DB 경로")
    parser.add_argument("--no-chroma", action="store_true", help="ChromaDB 내보내기 건너뛰기")
    args = parser.parse_args()

    out_dir  = Path(args.out)
    db_path  = Path(args.db)

    print("=" * 50)
    print("  데이터 내보내기")
    print("=" * 50)

    # SQLite 내보내기
    print("\n[1/2] essays.db → CSV")
    counts = export_sqlite(db_path, out_dir)
    for name, n in counts.items():
        print(f"  ✅ {name}.csv  {n:,}건 → {out_dir / (name + '.csv')}")

    # ChromaDB 내보내기
    if not args.no_chroma:
        print("\n[2/2] chroma_db → CSV")
        n = export_chroma(out_dir)
        if n:
            print(f"  ✅ chroma_docs.csv  {n:,}건 → {out_dir / 'chroma_docs.csv'}")
    else:
        print("\n[2/2] ChromaDB 내보내기 건너뜀 (--no-chroma)")

    print(f"\n📁 출력 위치: {out_dir.resolve()}")
    print("  · Excel에서 열 때 UTF-8 BOM 인코딩으로 저장 (자동 인식)")
    print("  · data/ 폴더는 .gitignore에 포함 (커밋 제외)")
    print("  · chroma_docs.csv로 임베딩 재구축 가능 (벡터 포함 X, 텍스트만)")
    print("=" * 50)


if __name__ == "__main__":
    main()
