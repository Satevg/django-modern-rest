import datetime as dt
from typing import Annotated, TypeAlias, final

import pydantic

DatabaseId: TypeAlias = Annotated[int, pydantic.Field(gt=0)]


@final
class PageQuery(pydantic.BaseModel):
    page_size: int = pydantic.Field(default=10, ge=1, le=100)
    page: int = pydantic.Field(default=1, ge=1)

    model_config = pydantic.ConfigDict(extra='forbid')


@final
class CursorPageQuery(pydantic.BaseModel):
    first: int | None = pydantic.Field(default=None, ge=1, le=100)
    last: int | None = pydantic.Field(default=None, ge=1, le=100)
    after: str | None = pydantic.Field(default=None, min_length=1)
    before: str | None = pydantic.Field(default=None, min_length=1)

    model_config = pydantic.ConfigDict(extra='forbid')

    @pydantic.model_validator(mode='after')
    def _validate_direction(self) -> 'CursorPageQuery':
        if self.first is None and self.last is None:
            self.first = 10
        elif self.first is not None and self.last is not None:
            raise ValueError("'first' and 'last' are mutually exclusive")
        return self


@final
class TagSchema(pydantic.BaseModel):
    name: str


@final
class RoleSchema(pydantic.BaseModel):
    name: str


class UserCreateSchema(pydantic.BaseModel):
    email: str
    role: RoleSchema
    tags: list[TagSchema]


@final
class UserSchema(UserCreateSchema):
    id: DatabaseId
    created_at: dt.datetime
