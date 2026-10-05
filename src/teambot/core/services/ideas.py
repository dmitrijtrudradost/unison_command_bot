"""Сервис идей этапа M1.

Сервис нормализует текст в приложении по правилу DB-7 и работает только через
``IdeaStore`` и ``IdeaIndex``. Это позволяет заменить простой индекс M1 на
векторный на M2.5 без изменения бизнес-логики.
"""

from teambot.core.errors import PermissionDenied, ValidationError
from teambot.core.models import Idea, IdeaFilter, NewIdea, Role, TeamContext, role_allows
from teambot.core.ports import IdeaIndex, IdeaStore

MAX_IDEA_LENGTH = 4000


def normalize_text(value: str) -> str:
    """Нормализует пользовательский текст для переносимого поиска.

    Аргументы:
        value: исходный текст.

    Возвращает:
        Строку с единичными пробелами и Unicode-нормализацией регистра через
        ``casefold``.
    """
    return " ".join(value.split()).casefold()


class IdeaService:
    """Создаёт и читает идеи в области рабочей группы."""

    def __init__(self, store: IdeaStore, index: IdeaIndex) -> None:
        """Создаёт сервис с хранилищем и заменяемым индексом."""
        self._store = store
        self._index = index

    async def add(
        self,
        ctx: TeamContext,
        text: str,
        *,
        source_message_id: str | None = None,
    ) -> Idea:
        """Создаёт и индексирует идею текущего участника.

        Исключения:
            PermissionDenied: роль ниже ``member``.
            ValidationError: текст пуст или превышает лимит.
        """
        _require_role(ctx, Role.MEMBER)
        clean_text = " ".join(text.split())
        if not clean_text or len(clean_text) > MAX_IDEA_LENGTH:
            raise ValidationError("Недопустимая длина текста идеи")
        tags = tuple(
            dict.fromkeys(
                token[1:].casefold()
                for token in clean_text.split()
                if token.startswith("#") and len(token) > 1
            )
        )
        idea = await self._store.create(
            ctx,
            NewIdea(
                text=clean_text,
                text_norm=normalize_text(clean_text),
                author_id=ctx.user_id,
                source_message_id=source_message_id,
                tags=tags,
            ),
        )
        await self._index.index(ctx, idea)
        return idea

    async def list(self, ctx: TeamContext, query: str | None = None) -> list[Idea]:
        """Возвращает активные идеи, при необходимости фильтруя по запросу."""
        _require_role(ctx, Role.VIEWER)
        query_norm = normalize_text(query) if query and query.strip() else None
        if query_norm is not None:
            matches = await self._index.find_similar(ctx, query_norm)
            return [match.idea for match in matches]
        return await self._store.list(ctx, IdeaFilter())


def _require_role(ctx: TeamContext, required: Role) -> None:
    if not role_allows(ctx.role, required):
        raise PermissionDenied
