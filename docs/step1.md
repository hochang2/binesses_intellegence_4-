# Step 1 — 데이터 수집 · 전처리 · 저장 방식 로컬 테스트

> 목적: 실제 데이터로 전처리 파이프라인을 검증하고,  
> 팀원에게 전달할 **최종 DB 스키마**를 확정한다.  
> 크롤링 후 팀원과 공유하기 전에 이 문서의 체크리스트를 모두 완료할 것.

---

## 파일 구조

```
essays.db                  ← 통합 DB (gitignore)
db.py                      ← 공용 스키마 + save/init 유틸
crawler.py                 ← 잡코리아 크롤러  (--test 옵션 있음)
crawler_linkareer.py       ← 링커리어 크롤러 (--test 옵션 있음)
preprocess.py              ← 전처리 파이프라인 (--dry-run 옵션 있음)
DESIGN.md                  ← 전체 설계서 (팀원 공유용)
step1.md                   ← 이 문서
```

---

## 체크리스트

### Phase A — 수집 (직접 실행)

- [ ] **A1** 잡코리아 테스트 수집
  ```
  python crawler.py --test
  ```
  → 삼성전자 1페이지분 수집, `essays.db` 생성 확인

- [ ] **A2** 링커리어 테스트 수집
  ```
  python crawler_linkareer.py --test
  ```
  → 삼성전자 최대 20건, 같은 `essays.db` 에 `source='linkareer'` 로 저장 확인

- [ ] **A3** DB 기본 확인
  ```
  python check_db.py
  ```
  → 아래 "빠른 확인 명령어" 참고

---

### Phase B — 전처리 검증

- [ ] **B1** 드라이런 (DB 없이 함수 단위 테스트)
  ```
  python preprocess.py --dry-run
  ```
  → 전 케이스 ✓ 확인 (이미 통과 확인됨)

- [ ] **B2** 실제 DB 전처리 실행
  ```
  python preprocess.py
  ```
  → `__RAW__` 행 Q&A 분리 + `question_clean` / `question_type` 채우기

- [ ] **B3** 전처리 결과 확인  
  아래 쿼리로 유형 분포 확인:
  ```sql
  SELECT question_type, COUNT(*) FROM qna
  WHERE is_valid=1 AND question_type IS NOT NULL
  GROUP BY question_type ORDER BY 2 DESC;
  ```

---

### Phase C — 품질 검토 & 스키마 확정

- [ ] **C1** 링커리어 Q&A 분리율 체크  
  분리 결과 `question_type = 'etc'` 비율이 **30% 미만**이면 OK

- [ ] **C2** 오매칭 체크  
  ```sql
  SELECT company, COUNT(*) FROM essays GROUP BY company ORDER BY company;
  ```
  엉뚱한 기업명이 들어왔는지 확인

- [ ] **C3** 스키마 확정  
  `db.py` 의 `init_db()` 가 팀원 요청서로 사용될 최종 스키마.  
  수정 사항이 있으면 반영 후 `DESIGN.md` 3절도 동기화.

- [ ] **C4** 팀원에게 `DESIGN.md` + `db.py` 공유

---

## 빠른 확인 명령어

```python
# python 인터랙티브 or 스크립트로 실행
import sqlite3
conn = sqlite3.connect("essays.db")

# 전체 통계
print("=== 통계 ===")
print("essays  :", conn.execute("SELECT COUNT(*) FROM essays").fetchone()[0])
print("qna     :", conn.execute("SELECT COUNT(*) FROM qna").fetchone()[0])

# 플랫폼별
for row in conn.execute(
    "SELECT source, COUNT(*) FROM essays GROUP BY source"
).fetchall():
    print(f"  {row[0]:12s}: {row[1]}건")

# 기업별
print("\n=== 기업별 ===")
for row in conn.execute(
    "SELECT company, source, COUNT(*) FROM essays GROUP BY company, source ORDER BY company"
).fetchall():
    print(f"  {row[0]:12s} [{row[1]}]: {row[2]}건")

# 잡코리아 샘플
print("\n=== 잡코리아 샘플 ===")
for row in conn.execute(
    "SELECT company, role, hire_type, year, university, spec_raw "
    "FROM essays WHERE source='jobkorea' LIMIT 3"
).fetchall():
    print(row)

# 링커리어 Q&A 분리 전 샘플
print("\n=== 링커리어 __RAW__ 샘플 ===")
for row in conn.execute(
    "SELECT e.company, LENGTH(q.answer) as len, q.answer[:200] "
    "FROM qna q JOIN essays e ON e.id=q.essay_id "
    "WHERE q.question='__RAW__' LIMIT 2"
).fetchall():
    print(row)

conn.close()
```

---

## 검증 기준

| 항목 | 통과 기준 |
|------|----------|
| 잡코리아 수집 | 삼성전자 5건 이상, Q&A 3쌍/건 이상 |
| 링커리어 수집 | 삼성전자 10건 이상, content 비어있지 않음 |
| Q&A 분리율 | 링커리어 전처리 후 2개 이상 Q&A로 분리된 비율 ≥ 60% |
| 유형 분류 | `question_type = 'etc'` 비율 < 30% |
| 텍스트 정제 | 홍보문구 제거 확인 (answer_clean 직접 확인) |
| 오매칭 | 엉뚱한 기업명 없음 |

---

## 완료 후 다음 단계

1. **팀원 DB 요청**: `DESIGN.md` 3절 스키마를 팀원에게 전달  
2. **Sprint 2** 시작: 본격 전처리 (전 기업 크롤링 완료 후 `python preprocess.py`)  
3. **Sprint 3** 준비: `requirements.txt` 에 `FlagEmbedding`, `chromadb` 추가  
4. **임베딩 실행**: `embed_pipeline.py` (별도 작성 예정, DESIGN.md 5절 참고)
