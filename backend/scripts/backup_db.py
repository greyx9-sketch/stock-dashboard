"""SQLite DB 백업.

**왜 필요한가.** DB 에 두 종류의 자산이 있고 무게가 다르다.

  - KRX 일별 시세 24만 행 — 날아가도 공공데이터포털에서 다시 받으면 된다(시간만 든다).
  - **공시 서술 분석 결과** — 다시 만들려면 건당 200~340원이 **또** 든다.

두 번째가 백업하는 이유다. 게다가 오라클 무료 인스턴스는 저사용이면 정지될 수 있고,
운영 중 실수나 잘못된 마이그레이션은 언제든 가능하다.

**왜 파일 복사가 아닌가.** 이 DB 는 WAL 모드로 돌고 앱이 계속 쓴다. `cp` 로 뜨면
`.db` 와 `-wal` 이 어긋난 순간을 잡아 복구할 수 없는 파일이 나올 수 있다.
파이썬 `sqlite3.Connection.backup()` 은 SQLite 의 **온라인 백업 API** 라
앱이 도는 중에도 일관된 사본을 만든다.

**이 백업의 한계** — 같은 디스크에 둔다. 앱 버그·실수·잘못된 마이그레이션은 막지만
**디스크나 인스턴스가 통째로 사라지면 같이 사라진다.** 원격 저장소로 보내려면 별도
자격증명이 필요해 여기서는 하지 않았다.

실행:
    python backend/scripts/backup_db.py              # 백업 + 검증 + 오래된 것 정리
    python backend/scripts/backup_db.py --list       # 가진 백업 보기
    python backend/scripts/backup_db.py --keep 30    # 보관 개수 바꾸기
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.base import DATABASE_URL  # noqa: E402

# 하루 한 번 도는 것을 전제로 2주. 52MB 원본이 압축되면 개당 10MB 안팎이라
# 14개도 150MB 수준이고, 서버 디스크는 39GB 가 남아 있다.
DEFAULT_KEEP = 14

BACKUP_DIR_NAME = "backups"


def db_path() -> Path:
    prefix = "sqlite:///"
    if not DATABASE_URL.startswith(prefix):
        raise SystemExit(f"SQLite 가 아닌 DB 는 이 스크립트로 백업할 수 없습니다: {DATABASE_URL}")
    return Path(DATABASE_URL[len(prefix) :])


def backup_dir(source: Path) -> Path:
    path = source.parent / BACKUP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _row_counts(path: Path) -> dict[str, int]:
    """테이블별 행 수. 백업이 실제로 열리고 읽히는지 확인하는 데 쓴다.

    `closing()` 을 쓰는 이유: `with sqlite3.connect(...)` 는 **연결을 닫지 않는다.**
    트랜잭션만 관리한다. 안 닫으면 윈도우에서 임시 폴더 정리가 실패하고, 리눅스에서는
    조용히 파일 핸들이 쌓인다(열린 파일도 unlink 되므로 겉보기엔 성공한다).
    """
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sorted(tables)}


def create_backup(source: Path, *, keep: int) -> Path:
    if not source.exists():
        raise SystemExit(f"DB 파일이 없습니다: {source}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backup_dir(source) / f"app-{stamp}.db.gz"

    # 1) 온라인 백업으로 일관된 사본을 임시 파일에 만든다.
    with tempfile.TemporaryDirectory() as tmpdir:
        raw = Path(tmpdir) / "app.db"
        with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(raw)) as dst:
                src.backup(dst)

        # 2) 사본을 열어 읽히는지 확인한다. 검증하지 않은 백업은 추측이다.
        counts = _row_counts(raw)
        if not counts:
            raise SystemExit("백업에 테이블이 없습니다. 원본을 확인해 주세요.")

        # 3) 압축해서 최종 위치로. 압축 중 실패하면 반쪽 파일이 남지 않도록 임시 이름을 쓴다.
        partial = target.with_suffix(target.suffix + ".part")
        with open(raw, "rb") as fin, gzip.open(partial, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout, length=1024 * 1024)
        partial.replace(target)

    original_mb = source.stat().st_size / 1_000_000
    packed_mb = target.stat().st_size / 1_000_000
    print(f"백업 완료: {target.name}  ({original_mb:.1f}MB → {packed_mb:.1f}MB)")
    print("  검증(테이블 행 수):")
    for table, n in counts.items():
        print(f"    {table:20} {n:>9,}")

    removed = prune(source, keep=keep)
    if removed:
        print(f"  오래된 백업 {removed}개 삭제 (보관 {keep}개)")
    return target


def prune(source: Path, *, keep: int) -> int:
    """최신 `keep` 개만 남긴다."""
    files = sorted(backup_dir(source).glob("app-*.db.gz"), reverse=True)
    doomed = files[keep:]
    for path in doomed:
        path.unlink()
    return len(doomed)


def list_backups(source: Path) -> None:
    files = sorted(backup_dir(source).glob("app-*.db.gz"), reverse=True)
    if not files:
        print("백업이 없습니다.")
        return
    total = sum(f.stat().st_size for f in files)
    print(f"백업 {len(files)}개 · 합계 {total / 1_000_000:.1f}MB · 위치 {backup_dir(source)}")
    for path in files:
        size = path.stat().st_size / 1_000_000
        when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  {path.name:28} {size:>6.1f}MB  {when}")
    print()
    print("되돌리는 방법 (서버):")
    print("  sudo systemctl stop stock-dashboard")
    print("  gunzip -c <백업파일> > /opt/stock/data/app.db")
    print("  sudo rm -f /opt/stock/data/app.db-wal /opt/stock/data/app.db-shm")
    print("  sudo chown stock:stock /opt/stock/data/app.db")
    print("  sudo systemctl start stock-dashboard")


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite DB 백업")
    parser.add_argument("--list", action="store_true", help="가진 백업만 보여준다")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help=f"보관 개수 (기본 {DEFAULT_KEEP})")
    args = parser.parse_args()

    source = db_path()
    if args.list:
        list_backups(source)
        return 0

    create_backup(source, keep=max(1, args.keep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
