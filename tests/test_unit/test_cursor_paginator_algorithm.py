"""Pure-algorithm tests for :mod:`dmr.pagination`.

These tests avoid Django's DB layer by exercising the cursor codec,
filter construction and argument validation directly.
"""

import base64
import json

import pytest
from django.db.models import Q

from dmr.pagination import CursorPaginator, InvalidCursorError


class _StubPaginator(CursorPaginator):  # type: ignore[type-arg]
    """Subclass that skips ``Paginator.__init__`` so no queryset is needed."""

    def __init__(
        self,
        *,
        ordering: tuple[str, ...],
        per_page: int = 10,
    ) -> None:
        self.ordering = ordering
        self.per_page = per_page


def test_encode_decode_roundtrip() -> None:
    """Values survive encoding and decoding (as strings)."""
    cursor = CursorPaginator._encode([1, 'foo', None])

    assert CursorPaginator._decode(cursor) == ['1', 'foo', None]


@pytest.mark.parametrize('values', [[1], ['a', 'b', 'c'], [None, None], [42]])
def test_encode_is_url_safe(values: list[object]) -> None:
    """Cursor strings do not use ``+`` / ``/`` padding characters."""
    cursor = CursorPaginator._encode(values)

    assert '+' not in cursor
    assert '/' not in cursor
    assert '=' not in cursor


def test_decode_rejects_non_list_payload() -> None:
    """Cursors that decode into non-list JSON raise ``InvalidCursorError``."""
    bad = (
        base64.urlsafe_b64encode(json.dumps({'k': 'v'}).encode())
        .decode('ascii')
        .rstrip('=')
    )

    with pytest.raises(InvalidCursorError):
        CursorPaginator._decode(bad)


def test_decode_rejects_invalid_base64() -> None:
    """Non-base64 input raises ``InvalidCursorError``."""
    with pytest.raises(InvalidCursorError):
        CursorPaginator._decode('definitely!not!base64!')


def test_build_filter_rejects_wrong_length() -> None:
    """Cursor length must match ``ordering`` arity."""
    paginator = _StubPaginator(ordering=('id', 'email'))
    cursor = CursorPaginator._encode(['only-one'])

    with pytest.raises(InvalidCursorError):
        paginator._build_filter(cursor, reverse=False)


def test_build_filter_forward_ascending() -> None:
    """Forward filter on ``id`` ascending becomes ``id > value``."""
    paginator = _StubPaginator(ordering=('id',))
    cursor = CursorPaginator._encode([5])

    q_filter = paginator._build_filter(cursor, reverse=False)

    assert q_filter == Q(id__gt='5')


def test_build_filter_forward_descending() -> None:
    """Forward filter on ``-id`` flips to ``id < value``."""
    paginator = _StubPaginator(ordering=('-id',))
    cursor = CursorPaginator._encode([5])

    q_filter = paginator._build_filter(cursor, reverse=False)

    assert q_filter == Q(id__lt='5')


def test_build_filter_reverse_mirrors_forward() -> None:
    """``reverse=True`` mirrors the forward predicate direction."""
    paginator = _StubPaginator(ordering=('id',))
    cursor = CursorPaginator._encode([5])

    q_filter = paginator._build_filter(cursor, reverse=True)

    assert q_filter == Q(id__lt='5')


def test_build_filter_multi_field() -> None:
    """Multi-field ordering creates the standard keyset disjunction."""
    paginator = _StubPaginator(ordering=('-created_at', 'id'))
    cursor = CursorPaginator._encode(['2024-01-01', 7])

    q_filter = paginator._build_filter(cursor, reverse=False)

    expected = Q(created_at__lt='2024-01-01') | (
        Q(created_at__exact='2024-01-01') & Q(id__gt='7')
    )
    assert q_filter == expected


def test_reverse_ordering() -> None:
    """Reversing ordering toggles the ``-`` prefix on each field."""
    paginator = _StubPaginator(ordering=('-created_at', 'id', '-name'))

    assert paginator._reverse_ordering() == (
        'created_at',
        '-id',
        'name',
    )


def test_page_size_requires_first_or_last() -> None:
    """``first`` or ``last`` must be supplied."""
    with pytest.raises(ValueError, match="'first' or 'last'"):
        CursorPaginator._page_size(None, None)


def test_page_size_rejects_both_first_and_last() -> None:
    """``first`` and ``last`` are mutually exclusive."""
    with pytest.raises(ValueError, match='mutually exclusive'):
        CursorPaginator._page_size(10, 5)


@pytest.mark.parametrize('size', [0, -1, -100])
def test_page_size_rejects_non_positive(size: int) -> None:
    """A cursor page size must be at least 1."""
    with pytest.raises(ValueError, match='>= 1'):
        CursorPaginator._page_size(size, None)


def test_page_size_accepts_first() -> None:
    """``first`` is returned unchanged when valid."""
    assert CursorPaginator._page_size(10, None) == 10


def test_page_size_accepts_last() -> None:
    """``last`` is returned unchanged when valid."""
    assert CursorPaginator._page_size(None, 7) == 7


def test_resolve_attr_simple() -> None:
    """Plain attribute access works."""
    class _Obj:
        id = 42

    assert CursorPaginator._resolve_attr(_Obj(), 'id') == 42


def test_resolve_attr_nested() -> None:
    """``foo__bar`` walks nested attributes."""
    class _Inner:
        name = 'leaf'

    class _Outer:
        inner = _Inner()

    assert (
        CursorPaginator._resolve_attr(_Outer(), 'inner__name') == 'leaf'
    )


def test_resolve_attr_short_circuits_on_none() -> None:
    """Nested resolution stops on the first ``None`` in the chain."""
    class _Outer:
        inner = None

    assert (
        CursorPaginator._resolve_attr(_Outer(), 'inner__name') is None
    )
