DEFAULT_PROVIDER = "gemini"

# (id, 설정 화면에 보여 줄 이름). id 는 keyring 의 사용자 이름이자 settings 의 ai_provider 값이다.
PROVIDERS = (
    ("gemini", "Gemini (기본 · 무료 티어 있음)"),
    ("claude", "Claude"),
    ("openai", "OpenAI"),
)

FREE_TIER_NOTICE = (
    "무료 티어(예: Gemini 무료 사용량)는 입력한 내용이 제공사의 제품 개선에 쓰일 수 있습니다 "
    "(제공사 약관 확인 필요). 이 앱이 보내는 것은 대상 기간의 일정·할 일 제목과 시간, 그리고 "
    "직접 입력한 문장뿐이며 메모 본문은 보내지 않습니다."
)
