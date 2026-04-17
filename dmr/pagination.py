import base64
import dataclasses
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Generic, TypeVar, cast

from django.core.paginator import Paginator
from django.db.models import Model, Q, QuerySet
from typing_extensions import override

_ModelT = TypeVar('_ModelT')
_RowT = TypeVar('_RowT', bound=Model)

if TYPE_CHECKING:
    _PaginatorBase = Paginator
else:
    # ``django.core.paginator.Paginator`` is not subscriptable at runtime,
    # but ``django-stubs`` types it as ``Paginator[_T]``. Expose a shim
    # that makes ``[_RowT]`` a no-op so the generic subclass works under
    # both type checkers and the interpreter.
    class _PaginatorBase(Paginator):  # noqa: WPS431
        def __class_getitem__(cls, item: object) -> type:
            return cls


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class Page(Generic[_ModelT]):
    """
    Default page model for serialization.

    Can be used when using pagination with ``django-modern-rest``.
    """

    number: int
    # Does not support `_SupportsPagination` type,
    # explicit type cast to `list` or `tuple` is required,
    # because it is hard to serialize complex `_SupportsPagination` protocol.
    object_list: Sequence[_ModelT]


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class Paginated(Generic[_ModelT]):
    """
    Helper type to serialize the default ``Paginator`` object.

    Django already ships a pagination system, we don't want to replicate it.
    So, we only provide metadata.
    See :class:`django.core.paginator.Paginator` for the exact API.
    """

    count: int
    num_pages: int
    per_page: int
    page: Page[_ModelT]


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class CursorPaginated(Generic[_ModelT]):
    """
    Response model for :class:`CursorPaginator`.

    Cursor pagination intentionally omits ``count`` / ``num_pages``
    to skip the extra ``COUNT(*)`` query that can be expensive on
    large tables.
    Walk the dataset via ``next_cursor`` and ``previous_cursor``.
    """

    per_page: int
    has_next: bool
    has_previous: bool
    next_cursor: str | None
    previous_cursor: str | None
    object_list: Sequence[_ModelT]


class InvalidCursorError(ValueError):
    """Raised when a cursor string cannot be decoded."""


class CursorPaginator(_PaginatorBase[_RowT], Generic[_RowT]):
    """
    Keyset (cursor-based) paginator over a Django :class:`QuerySet`.

    Subclass of :class:`django.core.paginator.Paginator` that replaces
    page-number navigation with cursor navigation via :meth:`page`.

    The ``ordering`` tuple is applied to the queryset in ``__init__``,
    so callers do not need to call ``.order_by(...)`` themselves. When
    the primary sort field is non-unique, include a tie-breaker
    (typically the primary key) to guarantee a stable cursor::

        CursorPaginator(
            User.objects.all(),
            per_page=10,
            ordering=('-created_at', 'id'),
        )

    The inherited ``count``, ``num_pages`` and page-number APIs are
    available but unused by the cursor flow; accessing ``count`` will
    still trigger a ``COUNT(*)`` query.

    Ordering fields are assumed to be ``NOT NULL``. ``None`` values
    are encoded into cursors but their filter semantics do not match
    database NULL ordering, which can yield inconsistent pages.

    The cursor filter algorithm is inspired by
    ``photocrowd/django-cursor-pagination`` (BSD-2-Clause).
    """

    def __init__(
        self,
        object_list: QuerySet[_RowT],
        per_page: int,
        *,
        ordering: Sequence[str],
    ) -> None:
        """Apply ``ordering`` to ``object_list`` and store it."""
        if not ordering:
            raise ValueError("'ordering' must be a non-empty sequence")
        self.ordering: tuple[str, ...] = tuple(ordering)
        self._queryset: QuerySet[_RowT] = object_list.order_by(
            *self.ordering,
        )
        super().__init__(  # pyright: ignore[reportUnknownMemberType]
            self._queryset,
            per_page,
        )

    @override
    def page(  # type: ignore[override]
        self,
        *,
        first: int | None = None,
        last: int | None = None,
        after: str | None = None,
        before: str | None = None,
    ) -> CursorPaginated[_RowT]:
        """
        Return a page of results selected by cursor.

        Exactly one of ``first`` or ``last`` must be provided.
        ``after`` / ``before`` are optional cursor strings previously
        produced by :meth:`cursor`.
        """
        size = self._page_size(first, last)
        queryset = self._apply_cursors(
            after,
            before,
            from_last=last is not None,
        )
        items = list(queryset[: size + 1])
        return self._materialize(
            items,
            size,
            first=first,
            last=last,
            after=after,
            before=before,
        )

    async def apage(
        self,
        *,
        first: int | None = None,
        last: int | None = None,
        after: str | None = None,
        before: str | None = None,
    ) -> CursorPaginated[_RowT]:
        """Async variant of :meth:`page`."""
        size = self._page_size(first, last)
        queryset = self._apply_cursors(
            after,
            before,
            from_last=last is not None,
        )
        items: list[_RowT] = [
            item async for item in queryset[: size + 1]
        ]
        return self._materialize(
            items,
            size,
            first=first,
            last=last,
            after=after,
            before=before,
        )

    def cursor(self, instance: _RowT) -> str:
        """Encode a cursor string pointing at ``instance``."""
        return self._encode(self._position(instance))

    @staticmethod
    def _page_size(first: int | None, last: int | None) -> int:
        if first is not None and last is not None:
            raise ValueError(
                "'first' and 'last' are mutually exclusive",
            )
        if first is not None:
            size = first
        elif last is not None:
            size = last
        else:
            raise ValueError(
                "One of 'first' or 'last' must be provided",
            )
        if size < 1:
            raise ValueError('Page size must be >= 1')
        return size

    def _apply_cursors(
        self,
        after: str | None,
        before: str | None,
        *,
        from_last: bool,
    ) -> QuerySet[_RowT]:
        queryset = self._queryset
        if after is not None:
            queryset = queryset.filter(
                self._build_filter(after, reverse=False),
            )
        if before is not None:
            queryset = queryset.filter(
                self._build_filter(before, reverse=True),
            )
        if from_last:
            queryset = queryset.order_by(*self._reverse_ordering())
        return queryset

    def _materialize(
        self,
        items: list[_RowT],
        size: int,
        *,
        first: int | None,
        last: int | None,
        after: str | None,
        before: str | None,
    ) -> CursorPaginated[_RowT]:
        has_extra = len(items) > size
        items = items[:size]
        if last is not None:
            items.reverse()
        if not items:
            return CursorPaginated(
                per_page=self.per_page,
                has_next=False,
                has_previous=False,
                next_cursor=None,
                previous_cursor=None,
                object_list=[],
            )
        if first is not None:
            has_next = has_extra
            has_previous = after is not None
        else:
            has_previous = has_extra
            has_next = before is not None
        return CursorPaginated(
            per_page=self.per_page,
            has_next=has_next,
            has_previous=has_previous,
            next_cursor=self.cursor(items[-1]) if has_next else None,
            previous_cursor=self.cursor(items[0]) if has_previous else None,
            object_list=items,
        )

    def _reverse_ordering(self) -> tuple[str, ...]:
        return tuple(
            field[1:] if field.startswith('-') else f'-{field}'
            for field in self.ordering
        )

    def _build_filter(self, cursor: str, *, reverse: bool) -> Q:
        values = self._decode(cursor)
        if len(values) != len(self.ordering):
            raise InvalidCursorError(
                f'Cursor has {len(values)} values, '
                f'expected {len(self.ordering)}',
            )
        q_final = Q()
        q_equal = Q()
        for field, raw_value in zip(self.ordering, values, strict=True):
            is_desc = field.startswith('-')
            name = field.removeprefix('-')
            if raw_value is None:
                q_equal &= Q(**{f'{name}__isnull': True})
                continue
            op = '__lt' if reverse != is_desc else '__gt'
            q_final |= q_equal & Q(**{f'{name}{op}': raw_value})
            q_equal &= Q(**{f'{name}__exact': raw_value})
        return q_final

    def _position(self, instance: _RowT) -> list[object]:
        return [
            self._resolve_attr(instance, field.removeprefix('-'))
            for field in self.ordering
        ]

    @staticmethod
    def _resolve_attr(instance: object, path: str) -> object:
        current: object = instance
        for part in path.split('__'):
            current = getattr(current, part)
            if current is None:
                return None
        return current

    @staticmethod
    def _encode(values: Sequence[object]) -> str:
        payload = [None if value is None else str(value) for value in values]
        raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

    @staticmethod
    def _decode(cursor: str) -> list[object]:
        try:
            padding = b'=' * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(cursor.encode('ascii') + padding)
            data: object = json.loads(raw.decode('utf-8'))
        except ValueError as exc:
            raise InvalidCursorError(f'Invalid cursor: {cursor!r}') from exc
        if not isinstance(data, list):
            raise InvalidCursorError(f'Invalid cursor payload: {cursor!r}')
        return cast('list[object]', data)
