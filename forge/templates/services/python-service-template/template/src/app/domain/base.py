from pydantic import BaseModel, ConfigDict


class BaseDomainModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        frozen=True,
        use_enum_values=True,
    )


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    skip: int
    limit: int
    has_more: bool
