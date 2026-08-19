"""pytest 공통 설정.

`app` 패키지를 찾을 수 있도록 `backend` 를 경로에 넣는다. 프로젝트에 별도 패키징 설정이
없어서(설치 없이 uvicorn 으로 바로 띄운다) 테스트에서도 같은 방식으로 맞춘다.

**이 테스트들은 네트워크를 부르지 않고 진짜 키도 필요 없다.** 순수 함수를 직접 부르거나,
외부를 부르는 지점을 가짜로 바꾼 뒤 라우터를 부른다.

외부 API 응답에 의존하는 확인은 `backend/scripts/check_*.py` 스크립트가 맡는다 —
그쪽은 실제 문서를 받아 눈으로 보는 용도이고, 이쪽은 되돌아오지 않아야 하는 것을 못 박는 용도다.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# **테스트는 진짜 DB 를 건드리지 않는다.** `app.models.base` 는 import 시점에 엔진을 만들므로
# 앱을 부르기 전에 여기서 주소를 바꿔 둬야 한다. 이 파일은 pytest 가 가장 먼저 읽는다.
os.environ["DATABASE_URL"] = "sqlite:///" + (
    Path(tempfile.mkdtemp(prefix="stock-test-")) / "test.db"
).as_posix()

# 라우터가 토스 클라이언트를 만들 수 있어야 한다. 실제로 호출하지는 않는다 —
# 외부를 부르는 지점은 테스트에서 전부 가짜로 바꾼다.
os.environ.setdefault("TOSS_CLIENT_ID", "test-id")
os.environ.setdefault("TOSS_CLIENT_SECRET", "test-secret")
