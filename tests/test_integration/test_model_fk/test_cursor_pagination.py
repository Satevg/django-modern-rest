"""End-to-end tests for the ``CursorPaginator`` flow in the test app."""

from http import HTTPStatus

import pytest
from django.urls import reverse
from faker import Faker

from dmr.test import DMRClient
from server.apps.model_fk.models import Role, User


def _create_users(faker: Faker, count: int) -> list[User]:
    role = Role.objects.create(name=faker.unique.name())
    return [
        User.objects.create(email=faker.unique.email(), role=role)
        for _ in range(count)
    ]


@pytest.mark.django_db
def test_cursor_first_page(dmr_client: DMRClient, faker: Faker) -> None:
    """First forward page returns ``first`` items with a ``next_cursor``."""
    _create_users(faker, count=5)

    response = dmr_client.get(
        reverse('api:model_fk:user-cursor'),
        query_params={'first': 2},
    )

    body = response.json()
    assert response.status_code == HTTPStatus.OK, body
    assert body['per_page'] == 2
    assert body['has_next'] is True
    assert body['has_previous'] is False
    assert body['next_cursor'] is not None
    assert body['previous_cursor'] is None
    assert len(body['object_list']) == 2


@pytest.mark.django_db
def test_cursor_walk_forward(dmr_client: DMRClient, faker: Faker) -> None:
    """Walking forward via ``next_cursor`` visits all rows exactly once."""
    users = _create_users(faker, count=5)
    seen_emails: set[str] = set()

    next_cursor: str | None = None
    for _ in range(5):
        params: dict[str, object] = {'first': 2}
        if next_cursor is not None:
            params['after'] = next_cursor
        body = dmr_client.get(
            reverse('api:model_fk:user-cursor'),
            query_params=params,
        ).json()
        seen_emails.update(row['email'] for row in body['object_list'])
        if not body['has_next']:
            break
        next_cursor = body['next_cursor']

    assert seen_emails == {user.email for user in users}


@pytest.mark.django_db
def test_cursor_walk_backward(dmr_client: DMRClient, faker: Faker) -> None:
    """``previous_cursor`` on the second page walks back to the first."""
    _create_users(faker, count=5)

    first = dmr_client.get(
        reverse('api:model_fk:user-cursor'),
        query_params={'first': 2},
    ).json()
    second = dmr_client.get(
        reverse('api:model_fk:user-cursor'),
        query_params={'first': 2, 'after': first['next_cursor']},
    ).json()

    # Walk back from page 2 using ``before``:
    back = dmr_client.get(
        reverse('api:model_fk:user-cursor'),
        query_params={'last': 2, 'before': second['previous_cursor']},
    ).json()

    assert back['object_list'] == first['object_list']
    assert back['has_next'] is True
    assert back['has_previous'] is False


@pytest.mark.django_db
def test_cursor_empty_dataset(dmr_client: DMRClient) -> None:
    """Empty queryset produces an empty response with no cursors."""
    body = dmr_client.get(
        reverse('api:model_fk:user-cursor'),
        query_params={'first': 5},
    ).json()

    assert body == {
        'per_page': 5,
        'has_next': False,
        'has_previous': False,
        'next_cursor': None,
        'previous_cursor': None,
        'object_list': [],
    }


@pytest.mark.django_db
def test_cursor_rejects_both_first_and_last(dmr_client: DMRClient) -> None:
    """Passing both ``first`` and ``last`` fails query validation."""
    response = dmr_client.get(
        reverse('api:model_fk:user-cursor'),
        query_params={'first': 2, 'last': 2},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_cursor_invalid_cursor_payload(
    dmr_client: DMRClient,
    faker: Faker,
) -> None:
    """Garbage ``after`` cursor becomes a 400 ``InvalidCursorError``."""
    _create_users(faker, count=2)

    response = dmr_client.get(
        reverse('api:model_fk:user-cursor'),
        query_params={'first': 2, 'after': 'not-a-real-cursor'},
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
