# Architectural Design Note: Bodhrik Service Booking Platform

### 1. Schema Shape & Rationale
The schema isolates core domains into dedicated relational entities: `users`, `bookings`, `reviews`, and `notifications`. Surrogate UUID primary keys prevent sequential ID harvesting and support distributed ID generation. Timezone-aware `timestamptz` columns enforce consistent UTC storage across boundaries. Database-level check constraints guarantee temporal validity (`end_time > start_time`), valid rating ranges (`1..5`), and participant differentiation (`customer_id != provider_id`), enforcing relational invariants independently of application-level validation.

### 2. Normalisation Tradeoffs
The transactional core is maintained in Third Normal Form (3NF) to eliminate update anomalies. Review aggregations (average ratings, distribution buckets) and provider availability are calculated on demand via indexed SQL aggregation rather than through denormalised summary columns on `users`. This eliminates write amplification and race conditions on high-frequency booking updates, while delegating CPU-heavy summarisation to asynchronous Redis queue workers.

### 3. RBAC Evolution for a Fourth Role
Introducing a fourth role—such as `AUDITOR` or `SUPPORT`—requires adding the enum member to `UserRole` and registering read-only permission scopes. Unlike `ADMIN`, an `AUDITOR` would possess platform-wide `SELECT` visibility across all bookings, reviews, and notifications, but strict `403 Forbidden` guards against mutating status, deleting reservations, or authoring reviews. Reusable dependency helpers (e.g., `require_roles(UserRole.ADMIN, UserRole.AUDITOR)`) enforce this declaratively.

### 4. RBAC for Nested Organisations
Supporting multi-tenant or hierarchical organisations (e.g., hospital networks with regional clinics and individual practitioners) entails introducing an `organisations` table with an adjacency list or closure table (`parent_id`) and an `organisation_memberships` table mapping `user_id`, `org_id`, and scoped roles (`ORG_ADMIN`, `CLINIC_MANAGER`, `STAFF`). API dependencies would resolve permissions hierarchically using PostgreSQL Row-Level Security (RLS) or tenant-filtered query scoping, verifying that the caller holds authority over the resource's organizational ancestor tree.

### 5. Production Safety Gaps
While resilient against standard failure modes, full enterprise production readiness requires:
- Token revocation / Redis blacklisting for immediate session invalidation upon logout or credential rotation.
- Distributed rate limiting (e.g., token bucket via Redis) on authentication and summarisation routes to guard against brute force and resource starvation.
- Dead-letter queues (DLQ) and worker heartbeats to capture and retry jobs lost if a worker terminates abruptly after dequeueing.

### 6. Migration Strategy
Database migrations adhere to an expand-and-contract pattern. New columns must be added as nullable or with safe defaults before backfilling, ensuring backward compatibility with running API instances. Alembic migrations execute as a single-head pipeline strictly during continuous deployment before traffic cutover.

### 7. Secrets Handling
In production, `.env` files are superseded by managed secret stores (e.g., AWS Secrets Manager, HashiCorp Vault). Secrets (`JWT_SECRET_KEY`, database credentials) are injected into container environments at runtime with automated rotation policies, never baked into Docker images or committed to version control.

### 8. Operational & Concurrency Concerns
PostgreSQL connection pooling (via PgBouncer) prevents thread starvation under high connection counts. Transaction isolation uses pessimistic row locking (`SELECT ... FOR UPDATE`) during booking creation to guarantee overlap-free reservations across concurrent requests.
