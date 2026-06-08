# src/app/services/tenant_service.py
"""
Business logic for tenant lifecycle management and provisioning.

The TenantService orchestrates realm assignment, Keycloak user creation,
and Redis cache population using a saga pattern with explicit compensation
on external service failures.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from uuid import UUID

from app.core.errors import AlreadyExistsError, NotFoundError
from app.data.repositories.realm_repository import RealmRepository
from app.data.repositories.tenant_repository import TenantRepository
from app.domain.realm import Realm, RealmCreate, RealmType
from app.domain.tenant import (
    PaginatedTenantResponse,
    Tenant,
    TenantCreate,
    TenantProvisionRequest,
    TenantRouteConfig,
    TenantStatus,
    TenantTier,
    TenantUpdate,
)
from app.events.models import TenantProvisioned, TenantReactivated, TenantSuspended
from app.events.publisher import EventPublisher
from app.services.keycloak_admin import KeycloakAdminClient
from app.services.redis_publisher import RedisPublisher
from forge_core.persistence import AsyncUnitOfWork

logger = logging.getLogger(__name__)

# Default rate limits per tier
DEFAULT_RATE_LIMITS: dict[str, int] = {
    TenantTier.FREE: 100,
    TenantTier.PRO: 600,
    TenantTier.ENTERPRISE: 6000,
}


class TenantService:
    def __init__(
        self,
        uow: AsyncUnitOfWork,
        keycloak: KeycloakAdminClient,
        redis_pub: RedisPublisher,
        gatekeeper_client_id: str = "gatekeeper",
    ) -> None:
        self._uow = uow
        self._keycloak = keycloak
        self._redis_pub = redis_pub
        self._gatekeeper_client_id = gatekeeper_client_id

    # ── Provisioning ──────────────────────────────────────────────────────

    async def provision(self, data: TenantProvisionRequest) -> Tenant:
        """
        Full provisioning workflow with saga-style compensation:

        1. Validate uniqueness (DB)
        2. Assign or create a Keycloak realm
        3. Create a Keycloak user
        4. Persist tenant to DB (atomic)
        5. Publish routing config to Redis (best-effort)

        On failure at step 2-3, compensate by cleaning up Keycloak.
        On failure at step 5, log error — recoverable via /sync-redis.
        """
        rate_limit = DEFAULT_RATE_LIMITS.get(data.tier, 100)

        # Step 1: Validate uniqueness
        async with self._uow as uow:
            tenant_repo = uow.repo(TenantRepository)
            if await tenant_repo.slug_exists(data.slug):
                raise AlreadyExistsError("Tenant", data.slug)
            if await tenant_repo.hostname_exists(data.hostname):
                raise AlreadyExistsError("Tenant hostname", data.hostname)

        # Steps 2-3: External service calls with compensation
        realm: Realm | None = None
        keycloak_user_id: str | None = None
        dedicated_realm_created = False

        try:
            if data.tier == TenantTier.ENTERPRISE:
                realm = await self._provision_dedicated_realm(data.slug, data.display_name)
                dedicated_realm_created = True
            else:
                realm = await self._assign_shared_realm()

            keycloak_user_id = await self._keycloak.create_user(
                realm_name=realm.name,
                username=data.admin_email,
                email=data.admin_email,
                password=data.admin_password,
            )
        except Exception:
            # Compensate: clean up the dedicated realm if we created one
            if dedicated_realm_created and realm:
                try:
                    await self._keycloak.delete_realm(realm.name)
                    logger.info("Compensated: deleted Keycloak realm '%s'", realm.name)
                except Exception as cleanup_exc:
                    logger.error(
                        "Failed to clean up Keycloak realm '%s': %s",
                        realm.name,
                        cleanup_exc,
                    )
            raise

        # Step 4: Persist to DB (atomic — realm + tenant in one transaction)
        async with self._uow as uow:
            realm_repo = uow.repo(RealmRepository)
            tenant_repo = uow.repo(TenantRepository)

            # Persist dedicated realm to DB (if created)
            if dedicated_realm_created:
                realm = await realm_repo.create(
                    RealmCreate(
                        name=realm.name,
                        realm_type=RealmType.DEDICATED,
                        keycloak_base_url=realm.keycloak_base_url,
                        client_id=realm.client_id,
                        client_secret=realm.client_secret,
                        max_tenants=1,
                    )
                )

            tenant = await tenant_repo.create(
                TenantCreate(
                    slug=data.slug,
                    display_name=data.display_name,
                    hostname=data.hostname,
                    admin_email=data.admin_email,
                    tier=data.tier,
                    rate_limit=rate_limit,
                    realm_id=realm.id,
                )
            )

            # Set provisioning metadata via TenantUpdate (no raw ORM)
            tenant = await tenant_repo.update(
                tenant.id,
                TenantUpdate(
                    status=TenantStatus.ACTIVE,
                    keycloak_user_id=keycloak_user_id,
                    provisioned_at=datetime.datetime.now(datetime.UTC),
                ),
            )

            # Write domain event to outbox (same transaction — at-least-once guarantee)
            event_pub = EventPublisher(uow.session)
            await event_pub.publish(
                TenantProvisioned(
                    tenant_id=str(tenant.id),
                    slug=data.slug,
                    hostname=data.hostname,
                    tier=data.tier,
                    realm_name=realm.name,
                    admin_email=data.admin_email,
                )
            )

        # Step 5: Publish to Redis (best-effort — recoverable via /sync-redis)
        try:
            route_config = self._build_route_config(tenant, realm)
            await self._redis_pub.publish_tenant_route(data.hostname, route_config)
            await self._redis_pub.publish_tenant_tier(data.slug, rate_limit)
        except Exception as exc:
            logger.error(
                "Redis publish failed for tenant '%s': %s — run /sync-redis to recover",
                data.slug,
                exc,
            )

        logger.info(
            "Provisioned tenant '%s' in realm '%s' (tier=%s)",
            data.slug,
            realm.name,
            data.tier,
        )
        return tenant

    async def _provision_dedicated_realm(self, slug: str, display_name: str) -> Realm:
        """Create a dedicated Keycloak realm + OIDC client. Returns an unsaved Realm."""
        realm_name = slug
        keycloak_base_url = self._keycloak._base_url

        await self._keycloak.create_realm(realm_name, display_name)
        client_secret = await self._keycloak.create_client(
            realm_name, self._gatekeeper_client_id, redirect_uris=["*"]
        )

        # Return a transient Realm (not persisted yet — DB persist happens in step 4)
        return Realm(
            id=uuid.uuid4(),  # placeholder, replaced on DB create
            name=realm_name,
            realm_type=RealmType.DEDICATED,
            keycloak_base_url=f"{keycloak_base_url}/realms",
            client_id=self._gatekeeper_client_id,
            client_secret=client_secret,
            max_tenants=1,
            is_active=True,
        )

    async def _assign_shared_realm(self) -> Realm:
        """Find a shared realm with capacity, or auto-provision one.

        Also ensures the Keycloak realm actually exists (idempotent create)
        in case the container was recreated and the DB record is stale.
        """
        async with self._uow as uow:
            realm_repo = uow.repo(RealmRepository)
            realm = await realm_repo.get_shared_with_capacity()

        if not realm:
            logger.info("No shared realm found — auto-provisioning 'shared-pool'")
            realm = await self._ensure_shared_realm_in_db()

        # Always ensure the Keycloak realm + client exist (idempotent)
        await self._ensure_keycloak_realm(realm.name)
        return realm

    async def _ensure_keycloak_realm(self, realm_name: str) -> None:
        """Ensure the realm and gatekeeper client exist in Keycloak (idempotent)."""
        await self._keycloak.create_realm(realm_name, "Shared")
        await self._keycloak.create_client(
            realm_name, self._gatekeeper_client_id, redirect_uris=["*"]
        )

    async def _ensure_shared_realm_in_db(self) -> Realm:
        """Create the shared realm DB record if it doesn't exist."""
        realm_name = "shared-pool"
        keycloak_base_url = self._keycloak._base_url

        async with self._uow as uow:
            realm_repo = uow.repo(RealmRepository)
            existing = await realm_repo.get_by_name(realm_name)
            if existing:
                return existing
            realm = await realm_repo.create(
                RealmCreate(
                    name=realm_name,
                    realm_type=RealmType.SHARED,
                    keycloak_base_url=f"{keycloak_base_url}/realms",
                    client_id=self._gatekeeper_client_id,
                    client_secret="managed-by-keycloak",
                    max_tenants=1000,
                )
            )
        logger.info("Auto-provisioned shared realm '%s' in DB", realm_name)
        return realm

    # ── CRUD ──────────────────────────────────────────────────────────────

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        status: TenantStatus | None = None,
        tier: TenantTier | None = None,
        realm_id: UUID | None = None,
    ) -> PaginatedTenantResponse:
        async with self._uow as uow:
            repo = uow.repo(TenantRepository)
            tenants = await repo.list_tenants(
                skip=skip,
                limit=limit,
                status=status,
                tier=tier,
                realm_id=realm_id,
            )
            total = await repo.count_tenants(status=status, tier=tier, realm_id=realm_id)
        return PaginatedTenantResponse(
            items=list(tenants),
            total=total,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total,
        )

    async def get(self, tenant_id: UUID) -> Tenant:
        async with self._uow as uow:
            repo = uow.repo(TenantRepository)
            tenant = await repo.get(tenant_id)
        if not tenant:
            raise NotFoundError("Tenant", tenant_id)
        return tenant

    async def get_by_slug(self, slug: str) -> Tenant:
        async with self._uow as uow:
            repo = uow.repo(TenantRepository)
            tenant = await repo.get_by_slug(slug)
        if not tenant:
            raise NotFoundError("Tenant", slug)
        return tenant

    async def update(self, tenant_id: UUID, data: TenantUpdate) -> Tenant:
        async with self._uow as uow:
            repo = uow.repo(TenantRepository)
            existing = await repo.get(tenant_id)
            if not existing:
                raise NotFoundError("Tenant", tenant_id)
            tenant = await repo.update(tenant_id, data)
        return tenant

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def suspend(self, tenant_id: UUID) -> Tenant:
        async with self._uow as uow:
            repo = uow.repo(TenantRepository)
            tenant = await repo.get(tenant_id)
            if not tenant:
                raise NotFoundError("Tenant", tenant_id)
            tenant = await repo.update(tenant_id, TenantUpdate(status=TenantStatus.SUSPENDED))

            event_pub = EventPublisher(uow.session)
            await event_pub.publish(
                TenantSuspended(
                    tenant_id=str(tenant.id),
                    slug=tenant.slug,
                    hostname=tenant.hostname,
                )
            )

        try:
            await self._redis_pub.remove_tenant_route(tenant.hostname, tenant.slug)
            await self._redis_pub.remove_tenant_tier(tenant.slug)
        except Exception as exc:
            logger.error(
                "Redis removal failed for tenant '%s': %s — run /sync-redis to recover",
                tenant.slug,
                exc,
            )

        logger.info("Suspended tenant '%s'", tenant.slug)
        return tenant

    async def reactivate(self, tenant_id: UUID) -> Tenant:
        async with self._uow as uow:
            repo = uow.repo(TenantRepository)
            realm_repo = uow.repo(RealmRepository)
            tenant = await repo.get(tenant_id)
            if not tenant:
                raise NotFoundError("Tenant", tenant_id)
            realm = await realm_repo.get(tenant.realm_id)
            if not realm:
                raise NotFoundError("Realm", tenant.realm_id)
            tenant = await repo.update(tenant_id, TenantUpdate(status=TenantStatus.ACTIVE))

            event_pub = EventPublisher(uow.session)
            await event_pub.publish(
                TenantReactivated(
                    tenant_id=str(tenant.id),
                    slug=tenant.slug,
                    hostname=tenant.hostname,
                    tier=tenant.tier,
                )
            )

        try:
            route_config = self._build_route_config(tenant, realm)
            await self._redis_pub.publish_tenant_route(tenant.hostname, route_config)
            await self._redis_pub.publish_tenant_tier(tenant.slug, tenant.rate_limit)
        except Exception as exc:
            logger.error(
                "Redis publish failed for tenant '%s': %s — run /sync-redis to recover",
                tenant.slug,
                exc,
            )

        logger.info("Reactivated tenant '%s'", tenant.slug)
        return tenant

    async def sync_all_to_redis(self) -> int:
        """Re-publish all active tenants to Redis (startup / recovery)."""
        async with self._uow as uow:
            tenant_repo = uow.repo(TenantRepository)
            realm_repo = uow.repo(RealmRepository)
            tenants = await tenant_repo.list_active()

            # Batch-fetch realms to avoid N+1 queries
            realm_ids = {t.realm_id for t in tenants}
            realms_by_id: dict[UUID, Realm] = {}
            for rid in realm_ids:
                r = await realm_repo.get(rid)
                if r:
                    realms_by_id[rid] = r

            routes: list[tuple[str, TenantRouteConfig]] = [
                (t.hostname, self._build_route_config(t, realms_by_id[t.realm_id]))
                for t in tenants
                if t.realm_id in realms_by_id
            ]

        if routes:
            return await self._redis_pub.publish_all(routes)
        return 0

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_route_config(tenant: Tenant, realm: Realm) -> TenantRouteConfig:
        return TenantRouteConfig(
            tenant_id=str(tenant.id),
            slug=tenant.slug,
            realm_type=realm.realm_type,
            realm_name=realm.name,
            issuer_url=f"{realm.keycloak_base_url}/{realm.name}",
            client_id=realm.client_id,
            client_secret=realm.client_secret,
            rate_limit=tenant.rate_limit,
        )
