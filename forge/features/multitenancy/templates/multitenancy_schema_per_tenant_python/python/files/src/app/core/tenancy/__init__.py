"""Tenant isolation runtime (schema_per_tenant).

Routes each request to a per-tenant Postgres schema by binding the connection's
``search_path`` for the request's transaction. Mirrors the ``shared_rls``
fragment's seams (config / resolver / middleware / engine listener) but swaps
the RLS GUC for schema routing. See :mod:`app.core.tenancy.schema`.
"""
