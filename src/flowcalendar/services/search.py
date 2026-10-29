"""일정 · 할 일 · 메모를 한꺼번에 찾는다 (제목/내용에 글자가 들어 있으면 일치, 대소문자는 구분하지 않는다).

DB를 읽기만 한다. 결과를 보여 주고 그 항목으로 이동하는 일은 화면 쪽이 한다.
"""

from dataclasses import dataclass, field
from datetime import date

from flowcalendar.data.memo_repo import MemoRepository
from flowcalendar.data.schedule_repo import ScheduleRepository
from flowcalendar.data.todo_repo import TodoRepository
from flowcalendar.domain.models import Schedule, Todo

MAX_PER_KIND = 30


@dataclass
class SearchResults:
    query: str
    schedules: list[Schedule] = field(default_factory=list)
    todos: list[Todo] = field(default_factory=list)
    memo_lines: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.schedules) + len(self.todos) + len(self.memo_lines)


def search_all(schedules: ScheduleRepository, todos: TodoRepository, memos: MemoRepository, query: str,
               today: date, limit: int = MAX_PER_KIND) -> SearchResults:
    query = query.strip()
    if not query:
        return SearchResults("")
    needle = query.casefold()
    memo_lines = [line.strip() for line in memos.get().splitlines() if needle in line.casefold()]
    return SearchResults(
        query,
        schedules.search(query, today, limit),
        todos.search(query, today, limit),
        memo_lines[:limit],
    )
