"""
공용 DB 스키마 및 유틸리티
두 크롤러(잡코리아, 링커리어)가 이 파일에서 import 해서 사용
"""
import sqlite3
from pathlib import Path

DB_PATH = Path("essays.db")

ORG_TYPE_MAP: dict[str, str] = {
    "삼성전자":   "corp",
    "현대자동차": "corp",
    "SK하이닉스": "corp",
    "LG전자":     "corp",
    "포스코":     "corp",
    "한국전력":   "public",
    "농협은행":   "bank",
    "기업은행":   "bank",
    "신한은행":   "bank",
    "우리은행":   "bank",
    "국민은행":   "bank",
    "하나은행":   "bank",
}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS essays (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,

            -- 플랫폼 식별
            source      TEXT NOT NULL DEFAULT 'jobkorea'
                            CHECK(source IN ('jobkorea', 'linkareer')),
            source_id   TEXT UNIQUE NOT NULL,   -- jobkorea: view_id, linkareer: lr_{id}

            -- 기업 정보
            company     TEXT NOT NULL,
            search_term TEXT,
            org_type    TEXT,                   -- 'corp' | 'bank' | 'public'

            -- 채용 정보
            role        TEXT,                   -- 직무/직렬
            hire_type   TEXT,                   -- '신입' | '경력' | '인턴'
            year        TEXT,
            season      TEXT,                   -- '상반기' | '하반기' | '수시'

            -- 지원자 스펙
            university  TEXT,
            major       TEXT,
            spec_raw    TEXT,                   -- 플랫폼 원본 스펙 문자열

            url         TEXT,
            crawled_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS qna (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            essay_id       INTEGER NOT NULL REFERENCES essays(id),

            q_num          TEXT,
            question       TEXT,
            answer         TEXT NOT NULL,

            -- 전처리 결과 (preprocess.py 가 채움, 초기엔 NULL)
            question_clean TEXT,
            answer_clean   TEXT,
            question_type  TEXT,                -- growth|motivation|experience|fit|personality|goal|etc

            char_count     INTEGER,
            is_valid       INTEGER DEFAULT 1    -- 0: 필터링됨
        );

        CREATE TABLE IF NOT EXISTS qna_embeddings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            qna_id      INTEGER UNIQUE NOT NULL REFERENCES qna(id),
            chroma_id   TEXT UNIQUE,
            model_name  TEXT,
            embedded_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_essays_company  ON essays(company);
        CREATE INDEX IF NOT EXISTS idx_essays_source   ON essays(source);
        CREATE INDEX IF NOT EXISTS idx_essays_org_type ON essays(org_type);
        CREATE INDEX IF NOT EXISTS idx_qna_essay_id    ON qna(essay_id);
        CREATE INDEX IF NOT EXISTS idx_qna_qtype       ON qna(question_type);
        CREATE INDEX IF NOT EXISTS idx_qna_valid       ON qna(is_valid);
    """)
    conn.commit()


def already_crawled(conn: sqlite3.Connection, source_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM essays WHERE source_id = ?", (source_id,)
    ).fetchone()
    return row is not None


def save_essay(conn: sqlite3.Connection, essay: dict) -> bool:
    """
    essays + qna 저장.
    중복(source_id)이면 스킵하고 False 반환.
    저장 성공 시 True 반환.
    """
    cur = conn.execute(
        """INSERT OR IGNORE INTO essays
           (source, source_id, company, search_term, org_type,
            role, hire_type, year, season, university, major, spec_raw, url, crawled_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            essay["source"],         essay["source_id"],
            essay["company"],        essay.get("search_term"),
            essay.get("org_type"),   essay.get("role"),
            essay.get("hire_type"),  essay.get("year"),
            essay.get("season"),     essay.get("university"),
            essay.get("major"),      essay.get("spec_raw"),
            essay.get("url"),        essay.get("crawled_at"),
        ),
    )
    if cur.lastrowid == 0:
        return False   # INSERT OR IGNORE skipped (중복)

    essay_id = cur.lastrowid
    conn.executemany(
        """INSERT INTO qna (essay_id, q_num, question, answer, char_count)
           VALUES (?,?,?,?,?)""",
        [
            (
                essay_id,
                qa.get("q_num", ""),
                qa.get("question", ""),
                qa.get("answer", ""),
                qa.get("char_count", len(qa.get("answer", ""))),
            )
            for qa in essay.get("qna", [])
        ],
    )
    conn.commit()
    return True


def db_stats(conn: sqlite3.Connection) -> dict:
    """현재 DB 통계 반환"""
    return {
        "essays":       conn.execute("SELECT COUNT(*) FROM essays").fetchone()[0],
        "qna":          conn.execute("SELECT COUNT(*) FROM qna").fetchone()[0],
        "jobkorea":     conn.execute("SELECT COUNT(*) FROM essays WHERE source='jobkorea'").fetchone()[0],
        "linkareer":    conn.execute("SELECT COUNT(*) FROM essays WHERE source='linkareer'").fetchone()[0],
        "preprocessed": conn.execute("SELECT COUNT(*) FROM qna WHERE question_clean IS NOT NULL").fetchone()[0],
    }
