"""AI 기능의 진입점. 설정(제공자, 모델)과 키(자격 증명 관리자)로 어댑터를 만들고, 변환/요약을 호출한다.

여기서 하는 일은 '읽기'뿐이다. 후보를 저장하는 일은 항상 사용자가 확인한 뒤 화면 쪽이 한다 (FR-AI-005).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime

from flowcalendar.ai import briefing, quick_add
from flowcalendar.ai.adapters import DEFAULT_MODELS, AIAdapter, create_adapter
from flowcalendar.ai.errors import AIError
from flowcalendar.ai.providers import DEFAULT_PROVIDER
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.settings_repo import SettingsRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.services.secrets import SecretError, SecretStore


# 브리핑은 앱을 켤 때 뜨는 보조 기능이라 오래 기다리지 않는다. 늦으면 코드로 계산한 요약을 바로 보여 준다.
BRIEFING_TIMEOUT = 10.0


def model_setting_key(provider: str) -> str:
    return f"ai_model_{provider}"


def pick_replacement(provider: str, old: str, models: list[str]) -> str | None:
    """쓰던 모델이 사라졌을 때 대신 쓸 모델: 이름이 가장 비슷한 것(같은 계열), 미리보기 판은 뒤로."""
    split = lambda name: set(re.split(r"[-_.:/ ]+", name.lower())) - {"", "models"}  # noqa: E731
    old_tokens = split(old)
    candidates = [m for m in models if m and m.removeprefix("models/") != old.removeprefix("models/")]
    if not candidates:
        return None

    def score(name: str):
        tokens = split(name)
        return (len(tokens & old_tokens), -len(tokens - old_tokens), "preview" not in name.lower(),
                name == DEFAULT_MODELS.get(provider), name)

    return max(candidates, key=score)


class AIService:
    def __init__(
        self,
        settings: SettingsRepository,
        secrets: SecretStore,
        *,
        transport=None,
        get_transport=None,
        clock: Callable[[], datetime] = datetime.now,
        adapter_factory: Callable[..., AIAdapter] = create_adapter,
    ):
        self.settings = settings
        self.secrets = secrets
        self._transport = transport
        self._get_transport = get_transport
        self._clock = clock
        self._factory = adapter_factory
        self._fallback: tuple[str, str, str] | None = None  # (제공사, 쓰던 모델, 대신 쓴 모델)

    # ---- 설정 ---------------------------------------------------------------------

    def provider(self) -> str:
        return self.settings.get("ai_provider") or DEFAULT_PROVIDER

    def model(self) -> str:
        return self.settings.get(model_setting_key(self.provider())).strip() or DEFAULT_MODELS.get(self.provider(), "")

    def has_key(self) -> bool:
        """키가 있어야 AI 화면(✨, 브리핑, 메모 변환)을 보여 준다 (FR-AI-003)."""
        try:
            return self.secrets.has(self.provider())
        except SecretError:
            return False

    # ---- 호출 ---------------------------------------------------------------------

    # AI 호출은 별도 스레드에서 돈다. SQLite 연결(설정)과 자격 증명 관리자는 만든 스레드에서만 안전하게 쓸 수 있으므로
    # 그것들을 읽는 일은 prepare() 로 화면 스레드에서 미리 끝내 두고, 별도 스레드에서는 *_with() 로 통신만 한다.

    def prepare(self) -> "AICall":
        """화면 스레드에서 부른다: 제공사, 모델, 키, 현재 시각을 읽어 고정한다. 키가 없으면 AIError('no_key')."""
        try:
            key = self.secrets.get(self.provider())
        except SecretError as exc:
            raise AIError("no_key", "자격 증명 관리자를 읽지 못했습니다") from exc
        if not key:
            raise AIError("no_key")
        return AICall(self.provider(), self.model(), key, self._clock())

    def _adapter(self, call: "AICall", **extra) -> AIAdapter:
        kwargs = {"transport": self._transport} if self._transport is not None else {}
        return self._factory(call.provider, call.key, call.model, **kwargs, **extra)

    def _complete(self, call: "AICall", system: str, user: str, schema: dict, name: str, **extra) -> dict:
        """AI 호출. 모델이 없어졌다는 오류(404)면 쓸 수 있는 모델 목록에서 비슷한 것을 골라 한 번만 다시 시도한다."""
        try:
            return self._adapter(call, **extra).complete_json(system, user, schema, name)
        except AIError as exc:
            if exc.kind != "model":
                raise
            try:
                new = pick_replacement(call.provider, call.model, self._adapter(call, **extra).list_models())
            except AIError:
                raise exc from None
            if not new:
                raise
            result = self._adapter(replace(call, model=new), **extra).complete_json(system, user, schema, name)
            self._fallback = (call.provider, call.model, new)
            return result

    def apply_fallback(self) -> str | None:
        """화면 스레드에서 부른다: 모델을 대신 쓴 일이 있었으면 그 모델을 설정에 저장하고 안내 문구를 돌려준다."""
        if self._fallback is None:
            return None
        provider, old, new = self._fallback
        self._fallback = None
        if self.provider() != provider or self.model() != old:
            return None  # 그 사이에 사용자가 직접 바꿨으면 건드리지 않는다
        self.settings.set(model_setting_key(provider), new)
        return f"AI 모델 '{old}'을(를) 더 쓸 수 없어 '{new}'(으)로 바꿨어요. 설정에서 다시 고를 수 있어요."

    def parse_text_with(self, call: "AICall", text: str) -> list[quick_add.Draft]:
        """사용자가 입력하거나 메모에서 고른 글 -> 일정/할 일 후보. DB 를 건드리지 않아 별도 스레드에서 불러도 된다."""
        if not text.strip():
            return []
        data = self._complete(
            call, quick_add.system_prompt(call.now), quick_add.user_prompt(text), quick_add.SCHEMA, "calendar_items"
        )
        return quick_add.drafts_from_response(data, call.now.date())

    def summarize_with(self, call: "AICall", data: briefing.BriefingData) -> str:
        result = self._complete(
            call, briefing.system_prompt(), briefing.build_input(data), briefing.SCHEMA, "briefing",
            timeout=BRIEFING_TIMEOUT, retry_delays=(),  # 오래 기다리거나 되풀이하지 않는다
        )
        return briefing.parse_summary(result)

    def list_models_for(self, provider: str, key: str) -> list[str]:
        """이 키로 쓸 수 있는 모델 이름들 (설정 화면의 '사용 가능한 모델 불러오기').
        DB 를 건드리지 않아 별도 스레드에서 불러도 되고, 키만 보내며 사용자 데이터는 보내지 않는다."""
        kwargs = {}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        if self._get_transport is not None:
            kwargs["get_transport"] = self._get_transport
        return self._factory(provider, key, "", **kwargs).list_models()

    # 같은 스레드에서 쓰는 간단한 호출 (테스트, 스크립트)
    def parse_text(self, text: str) -> list[quick_add.Draft]:
        return [] if not text.strip() else self.parse_text_with(self.prepare(), text)

    def summarize(self, data: briefing.BriefingData) -> str:
        return self.summarize_with(self.prepare(), data)


@dataclass(frozen=True)
class AICall:
    """한 번의 AI 호출에 필요한 값. 화면 스레드에서 읽어 두고 별도 스레드로 넘긴다."""

    provider: str
    model: str
    key: str = field(repr=False)  # 로그나 오류 출력에 키가 찍히지 않게
    now: datetime


def find_duplicates(drafts: list[quick_add.Draft], schedules: ScheduleRepository, todos: TodoRepository) -> list[bool]:
    """후보마다 '같은 제목이 같은 날에 이미 있는가'. 메모를 여러 번 변환해도 중복 등록을 막는 데 쓴다."""
    result = []
    quick_titles = {t.title.strip().casefold() for t in todos.list_quick()}
    for d in drafts:
        title = d.title.strip().casefold()
        if d.is_schedule:
            day = d.day
            exists = any(o.title.strip().casefold() == title for o in schedules.list_occurrences(day, day) if o.date == day)
        elif d.day is None:
            exists = title in quick_titles
        else:
            exists = any(t.title.strip().casefold() == title for t in todos.list_daily(d.day, d.day))
        result.append(exists)
    return result
