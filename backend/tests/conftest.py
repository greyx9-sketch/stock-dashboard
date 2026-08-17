"""pytest 공통 설정.

`app` 패키지를 찾을 수 있도록 `backend` 를 경로에 넣는다. 프로젝트에 별도 패키징 설정이
없어서(설치 없이 uvicorn 으로 바로 띄운다) 테스트에서도 같은 방식으로 맞춘다.

**이 테스트들은 네트워크를 부르지 않고 API 키도 필요 없다.** 전부 순수 함수 대상이다.
외부 API 응답에 의존하는 확인은 `backend/scripts/check_*.py` 스크립트가 맡는다 —
그쪽은 실제 문서를 받아 눈으로 보는 용도이고, 이쪽은 되돌아오지 않아야 하는 것을 못 박는 용도다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
