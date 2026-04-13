from pydantic import BaseModel


class User(BaseModel):
    id: str
    username: str
    email: str
    first_name: str
    last_name: str
    roles: list[str]
    customer_id: str
    org_id: str | None = None
    service_account: bool = False
    token: dict
