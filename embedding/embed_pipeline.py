"""
임베딩 파이프라인 v1
- 모델  : BAAI/bge-m3  (dense 1024dim, cosine)
- 저장  : ChromaDB 로컬 (./chroma_db)
- 재실행 안전: qna_embeddings 테이블 기준으로 기임베딩 행 스킵
- 실행  : python embed_pipeline.py
- 테스트: python embed_pipeline.py --test   (100건만)
"""

import sys
import io
import time
import sqlite3
import logging
import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
from tqdm import tqdm

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 프로젝트 루트를 Python 경로에 추가 (crawling.db import 용)
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from crawling.db import DB_PATH

# ── 설정 ──────────────────────────────────────────────────────────────────────

MODEL_NAME  = "BAAI/bge-m3"
CHROMA_PATH = "./chroma_db"
COLLECTION  = "cover_letters"

# GPU 있으면 64, CPU 전용이면 16
BATCH_SIZE  = 16

# ── 로깅 ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("embed_pipeline.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── 모델 ─────────────────────────────────────────────────────────────────────

def load_model():
    """BGE-M3 로드 (sentence-transformers).
    FlagEmbedding 설치돼 있으면 더 빠른 추론 가능하나 여기선 ST 사용.
    """
    from sentence_transformers import SentenceTransformer
    log.info(f"모델 로드 중: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    log.info("모델 로드 완료")
    return model


def embed_batch(model, texts: list[str]) -> np.ndarray:
    """dense 임베딩 + L2 정규화 → (N, 1024) float32 배열"""
    return model.encode(
        texts,
        normalize_embeddings=True,   # cosine 검색 시 dot product = cosine
        show_progress_bar=False,
        batch_size=BATCH_SIZE,
    )


# ── ChromaDB ──────────────────────────────────────────────────────────────────

def get_collection():
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    col = client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    log.info(f"ChromaDB 컬렉션 '{COLLECTION}' 준비 | 기존 벡터: {col.count()}개")
    return col


# ── 텍스트 조합 ───────────────────────────────────────────────────────────────

def make_text(question_clean: str | None, answer_clean: str | None) -> str:
    """
    [질문]\n[답변] 형태로 조합.
    질문이 없는 행(링커리어 분리 실패 등)은 답변만 사용.
    """
    q = (question_clean or "").strip()
    a = (answer_clean   or "").strip()
    return f"{q}\n{a}" if q else a


# ── SQLite ────────────────────────────────────────────────────────────────────

def load_pending(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    """qna_embeddings 에 없는 미임베딩 행만 가져온다."""
    sql = """
        SELECT
            q.id            AS qna_id,
            q.essay_id,
            q.question_clean,
            q.answer_clean,
            q.question_type,
            q.char_count,
            e.source,
            e.company,
            e.org_type,
            e.role,
            e.hire_type,
            e.year,
            e.season,
            e.university,
            e.major
        FROM  qna            q
        JOIN  essays         e   ON  e.id     = q.essay_id
        LEFT JOIN qna_embeddings qe ON qe.qna_id = q.id
        WHERE q.is_valid       = 1
          AND q.question_clean IS NOT NULL
          AND qe.id            IS NULL
        ORDER BY q.id
    """
    if limit:
        sql += f" LIMIT {limit}"

    cols = [
        "qna_id", "essay_id", "question_clean", "answer_clean", "question_type",
        "char_count", "source", "company", "org_type", "role", "hire_type",
        "year", "season", "university", "major",
    ]
    return [dict(zip(cols, r)) for r in conn.execute(sql).fetchall()]


def mark_done(conn: sqlite3.Connection, qna_ids: list[int], chroma_ids: list[str]) -> None:
    now = datetime.now().isoformat()
    conn.executemany(
        """INSERT OR IGNORE INTO qna_embeddings
               (qna_id, chroma_id, model_name, embedded_at)
           VALUES (?, ?, ?, ?)""",
        [(qid, cid, MODEL_NAME, now) for qid, cid in zip(qna_ids, chroma_ids)],
    )
    conn.commit()


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main(test_mode: bool = False):
    limit = 100 if test_mode else None
    if test_mode:
        log.info("=== 테스트 모드: 최대 100건 ===")

    conn  = sqlite3.connect(DB_PATH)
    col   = get_collection()
    model = load_model()

    pending = load_pending(conn, limit=limit)
    total   = len(pending)
    log.info(f"임베딩 대상: {total}건")

    if total == 0:
        log.info("모두 임베딩 완료 상태입니다.")
        conn.close()
        return

    done = failed = 0
    t0   = time.time()

    pbar = tqdm(total=total, unit="건", desc="임베딩", ncols=80)

    for start in range(0, total, BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        texts = [make_text(r["question_clean"], r["answer_clean"]) for r in batch]

        # ── 임베딩 ──
        try:
            vecs = embed_batch(model, texts)
        except Exception as e:
            log.error(f"임베딩 오류 (idx={start}): {e}")
            failed += len(batch)
            pbar.update(len(batch))
            continue

        chroma_ids = [f"qna_{r['qna_id']}" for r in batch]
        qna_ids    = [r["qna_id"] for r in batch]

        # ChromaDB 메타데이터 — 전부 str/int (float 금지)
        metadatas = [
            {
                "qna_id":        int(r["qna_id"]),
                "essay_id":      int(r["essay_id"]),
                "source":        r["source"]        or "",
                "company":       r["company"]        or "",
                "org_type":      r["org_type"]       or "",
                "role":          r["role"]           or "",
                "hire_type":     r["hire_type"]      or "",
                "year":          r["year"]           or "",
                "season":        r["season"]         or "",
                "question_type": r["question_type"]  or "",
                "university":    r["university"]     or "",
                "major":         r["major"]          or "",
                "char_count":    int(r["char_count"] or 0),
            }
            for r in batch
        ]

        # ── ChromaDB upsert ──
        try:
            col.upsert(
                ids=chroma_ids,
                embeddings=vecs.tolist(),
                metadatas=metadatas,
                documents=texts,        # 원문 보관 (검색 결과에서 바로 꺼낼 수 있음)
            )
            mark_done(conn, qna_ids, chroma_ids)
            done += len(batch)
        except Exception as e:
            log.error(f"ChromaDB upsert 오류 (idx={start}): {e}")
            failed += len(batch)

        pbar.update(len(batch))

        # 100배치마다 중간 속도 로그
        if (start // BATCH_SIZE + 1) % 100 == 0:
            elapsed = time.time() - t0
            speed   = done / elapsed
            eta_min = (total - done) / speed / 60 if speed > 0 else 0
            log.info(f"  [{done}/{total}] 속도={speed:.1f}건/s  ETA={eta_min:.1f}분")

    pbar.close()

    elapsed = time.time() - t0
    log.info(f"\n{'='*50}")
    log.info(f"완료: 성공={done}건  실패={failed}건  소요={elapsed/60:.1f}분")
    log.info(f"ChromaDB 총 벡터: {col.count()}개")
    log.info(f"평균 속도: {done/elapsed:.1f}건/s")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="최대 100건만 임베딩")
    args = parser.parse_args()
    main(test_mode=args.test)
