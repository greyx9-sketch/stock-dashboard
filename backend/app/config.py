"""환경변수(.env) 로드.

키는 전부 이 파일을 통해서만 읽는다. 코드 어디에도 키를 직접 적지 않는다.

모든 키를 선택값(기본 None)으로 둔다. 프로젝트를 단계별로 만들어 나가는 동안
아직 발급받지 않은 키가 있는 것이 정상이고, 그 상태에서도 서버는 떠야 하기 때문이다.
키가 실제로 필요한 시점에 각 클라이언트가 `require()` 로 확인한다.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 이 파일 → app → backend → 프로젝트 루트. .env 는 루트에 있다.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 토스증권 Open API (1단계)
    toss_client_id: str | None = None
    toss_client_secret: str | None = None

    # OpenDART — 국내 공시·재무
    dart_api_key: str | None = None

    # SEC EDGAR — 미국 공시 (4단계). 키가 아니라 "이름 이메일" 형식의 신원 표기다.
    sec_user_agent: str | None = None

    # Anthropic — 10-K 서술 분석 (6단계)
    anthropic_api_key: str | None = None

    # 외부 공개용 공용 비밀번호 (8단계)
    site_password: str | None = None

    # 앱 설정
    app_env: str = "development"
    database_url: str = "sqlite:///./data/app.db"

    def require(self, name: str) -> str:
        """키가 있어야만 진행 가능한 지점에서 쓴다.

        없으면 무엇을 어디서 발급받아 어디에 넣어야 하는지 알려주고 멈춘다.
        빈 값으로 조용히 넘어가면 원인을 알 수 없는 401/403 으로 돌아온다.
        """
        value = getattr(self, name, None)
        if not value:
            raise RuntimeError(
                f"{name.upper()} 가 비어 있습니다. "
                f"프로젝트 루트의 .env 파일에서 {name.upper()}= 뒤에 값을 넣어 주세요. "
                f"어디서 발급받는지는 .env.example 의 주석과 TODO.md 에 적혀 있습니다."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """설정을 한 번만 읽어 재사용한다."""
    return Settings()
