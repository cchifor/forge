from contextvars import ContextVar, Token

customer_id_context: ContextVar[str | None] = ContextVar("customer_id_context", default=None)
user_id_context: ContextVar[str | None] = ContextVar("user_id_context", default=None)


def get_customer_id() -> str:
    customer_id = customer_id_context.get()
    if customer_id is None:
        raise ValueError("customer_id is not set in the current context.")
    return customer_id


def get_user_id() -> str:
    user_id = user_id_context.get()
    if user_id is None:
        raise ValueError("user_id is not set in the current context.")
    return user_id


def set_context(customer_id: str, user_id: str) -> list[Token]:
    tokens = [customer_id_context.set(customer_id), user_id_context.set(user_id)]
    return tokens


def reset_context(tokens: list[Token]):
    customer_id_context.reset(tokens[0])
    user_id_context.reset(tokens[1])
