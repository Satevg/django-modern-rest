import pydantic
from django.contrib.auth.models import User

from dmr import Controller, Query
from dmr.pagination import CursorPaginated, CursorPaginator
from dmr.plugins.pydantic import PydanticSerializer


class _User(pydantic.BaseModel):
    id: int
    username: str


class _CursorPageQuery(pydantic.BaseModel):
    first: int | None = pydantic.Field(default=None, ge=1, le=100)
    last: int | None = pydantic.Field(default=None, ge=1, le=100)
    after: str | None = None
    before: str | None = None


_UserList = pydantic.TypeAdapter(list[_User])


class UsersController(Controller[PydanticSerializer]):
    def get(
        self,
        parsed_query: Query[_CursorPageQuery],
    ) -> CursorPaginated[_User]:
        paginator = CursorPaginator(
            User.objects.all(),
            per_page=parsed_query.first or parsed_query.last or 10,
            ordering=('-date_joined', 'id'),
        )
        page = paginator.page(
            first=parsed_query.first,
            last=parsed_query.last,
            after=parsed_query.after,
            before=parsed_query.before,
        )
        return CursorPaginated(
            per_page=page.per_page,
            has_next=page.has_next,
            has_previous=page.has_previous,
            next_cursor=page.next_cursor,
            previous_cursor=page.previous_cursor,
            object_list=_UserList.validate_python(
                page.object_list,
                from_attributes=True,
            ),
        )


# run: {"controller": "UsersController", "method": "get", "url": "/api/users/", "query": "?first=2", "populate_db": true}  # noqa: ERA001, E501
# openapi: {"controller": "UsersController", "openapi_url": "/docs/openapi.json"}  # noqa: ERA001, E501
