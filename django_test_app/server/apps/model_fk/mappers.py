from typing import final

import attrs
from django.core.paginator import EmptyPage, Paginator
from django.db.models import QuerySet

from dmr.pagination import (
    CursorPaginated,
    CursorPaginator,
    Page,
    Paginated,
)
from server.apps.model_fk.models import Role, Tag, User
from server.apps.model_fk.serializers import (
    CursorPageQuery,
    PageQuery,
    RoleSchema,
    TagSchema,
    UserSchema,
)


@final
@attrs.define(frozen=True)
class TagMap:
    def single(self, tag: Tag) -> TagSchema:
        return TagSchema(name=tag.name)

    def multiple(self, tags: QuerySet[Tag]) -> list[TagSchema]:
        return [self.single(tag) for tag in tags]


@final
@attrs.define(frozen=True)
class RoleMap:
    def single(self, role: Role) -> RoleSchema:
        return RoleSchema(name=role.name)


@final
@attrs.define(frozen=True)
class UserMap:
    _role: RoleMap
    _tag: TagMap

    def single(self, user: User) -> UserSchema:
        return UserSchema(
            id=user.pk,
            email=user.email,
            created_at=user.created_at,
            role=self._role.single(user.role),
            tags=self._tag.multiple(user.tags.all()),
        )

    def multiple(
        self,
        users: QuerySet[User],
        parsed_query: PageQuery,
    ) -> Paginated[UserSchema]:
        # Logic to paginate users:
        paginator = Paginator(users, parsed_query.page_size)
        try:
            object_list = [
                self.single(user)
                for user in paginator.page(parsed_query.page).object_list
            ]
        except EmptyPage:
            object_list = []
        return Paginated(
            count=paginator.count,
            num_pages=paginator.num_pages,
            per_page=paginator.per_page,
            page=Page(
                number=parsed_query.page,
                object_list=object_list,
            ),
        )

    def multiple_cursor(
        self,
        users: QuerySet[User],
        parsed_query: CursorPageQuery,
    ) -> CursorPaginated[UserSchema]:
        per_page = parsed_query.first or parsed_query.last or 10
        paginator = CursorPaginator(
            users,
            per_page=per_page,
            ordering=('-created_at', 'id'),
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
            object_list=[
                self.single(user)
                for user in page.object_list
            ],
        )
