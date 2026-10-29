"""응답 형식(JSON 스키마)을 한 가지로 적어 두고, 제공사마다 요구하는 모양으로 바꿔 준다.

공통 형식은 JSON 스키마의 부분집합에 `nullable: true` 를 더한 것이다:
  {"type": "object", "properties": {...}, "required": [...]}
  {"type": "string", "enum": [...], "nullable": true}
"""

import copy


def _walk(node, fn):
    """하위 항목을 먼저 바꾸고 마지막에 이 항목을 바꾼다. (이 항목의 type 을 먼저 바꾸면 하위 항목을 못 찾는다)"""
    node = copy.copy(node)
    if node.get("type") == "object":
        node["properties"] = {k: _walk(v, fn) for k, v in node.get("properties", {}).items()}
    if node.get("type") == "array" and "items" in node:
        node["items"] = _walk(node["items"], fn)
    return fn(node)


def to_gemini(schema: dict) -> dict:
    """Gemini responseSchema: 대문자 타입 이름, nullable 은 그대로 쓴다."""

    def convert(node):
        node["type"] = node["type"].upper()
        node.pop("additionalProperties", None)
        return node

    return _walk(schema, convert)


def to_json_schema(schema: dict) -> dict:
    """일반 JSON 스키마 (Claude 도구 입력): nullable -> type 배열."""

    def convert(node):
        if node.pop("nullable", False):
            node["type"] = [node["type"], "null"]
            if "enum" in node and None not in node["enum"]:
                node["enum"] = [*node["enum"], None]
        return node

    return _walk(schema, convert)


def to_openai_strict(schema: dict) -> dict:
    """OpenAI strict 모드: 모든 속성이 required, additionalProperties=false, nullable -> type 배열."""

    def convert(node):
        is_object = node.get("type") == "object"  # type 을 배열로 바꾸기 전에 확인한다
        if node.pop("nullable", False):
            node["type"] = [node["type"], "null"]
            if "enum" in node and None not in node["enum"]:
                node["enum"] = [*node["enum"], None]
        if is_object:
            node["required"] = list(node.get("properties", {}))
            node["additionalProperties"] = False
        return node

    return _walk(schema, convert)
