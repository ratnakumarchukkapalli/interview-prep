# Section 8: PostgreSQL HA & pgBackRest

### 8.1 PostgreSQL Fundamentals — What Every DevOps Engineer Must Know

PostgreSQL is an open-source, ACID-compliant relational database. At Confirmation, it's the backbone — every microservice (pricing, forms, selfreg, nucleus, record, etc.) has its own dedicated database inside a shared PostgreSQL cluster.

**Key Concepts:**

| Concept | What It Is | Why It Matters |
|---------|-----------|----------------|
| **ACID** | Atomicity, Consistency, Isolation, Durability | Guarantees data integrity — a bank audit confirmation either fully commits or fully rolls back |
| **WAL (Write-Ahead Log)** | Every change writes to WAL *before* the data file | Crash recovery + replication — replay WAL to recover or replicate data |
| **MVCC** | Multi-Version Concurrency Control | Readers don't block writers — each transaction sees a snapshot, not live data |
| **Vacuum** | Cleans up dead rows left by MVCC | Without vacuum, table bloat grows and queries slow down |
| **Shared Buffers** | In-memory cache of data pages | Reduces disk I/O — we set `shared_buffers: 16GB` on r5.4xlarge (128GB RAM) |
| **Work Mem** | Memory per sort/hash operation | `work_mem: 256MB` — too low = disk sorts, too high = OOM with many connections |
| **WAL Level** | Controls how much info goes into WAL | `replica` for streaming replication, `logical` for Fivetran CDC |
| **pg_hba.conf** | Host-based authentication file | Controls WHO can connect from WHERE with WHAT auth method |
| **Connection Pooling** | Reuse database connections | PgBouncer in front of PostgreSQL — avoids forking a process per connection |

**Interview Answer — "Explain WAL and why it matters":**

> "WAL stands for Write-Ahead Log. Every change to PostgreSQL data is first written to the WAL file before the actual data pages. This gives us two critical capabilities:
>
> 1. **Crash recovery**: If the server crashes mid-transaction, PostgreSQL replays the WAL on startup to recover committed transactions
> 2. **Replication**: WAL records are streamed to replicas for high availability — this is called streaming replication
>
> In our setup, we also use WAL for a third purpose: **Change Data Capture**. With `wal_level=logical`, PostgreSQL decodes the WAL into logical changes that Fivetran reads to replicate our operational data to the data warehouse. The trade-off is that logical WAL generates more data than replica WAL, so we only enable it in environments where Fivetran runs."

---

### 8.2 PostgreSQL HA Architecture — Crunchy Postgres Operator + Patroni

We run PostgreSQL on Kubernetes using the **Crunchy Data PostgreSQL Operator** (PGO). The operator manages the entire lifecycle — provisioning, HA failover, backups, user management — through a Kubernetes CRD called `PostgresCluster`.

**Architecture:**

```
┌─────────────────────────────────────────────────┐
│           Crunchy Postgres Operator (PGO)        │
│   Watches PostgresCluster CRDs, manages pods     │
└────────────────┬────────────────────────────────┘
                 │ manages
    ┌────────────┴───────────────┐
    │                            │
┌───▼──────────┐    ┌───────────▼───┐
│ Instance-1    │    │ Instance-2     │
│ (Primary)     │    │ (Replica)      │
│ PostgreSQL 16 │──▶│ PostgreSQL 16  │
│ Patroni       │WAL│ Patroni        │
│ 200Gi PVC     │   │ 200Gi PVC      │
│ r5.4xlarge    │   │ r5.4xlarge     │
└───────┬───────┘    └───────────────┘
        │
        ▼
┌──────────────────┐    ┌──────────────────┐
│ pgBackRest Repo  │───▶│ S3 Outposts      │
│ 200Gi PVC        │sync│ Off-cluster copy │
└──────────────────┘    └──────────────────┘
```

**How Patroni Works:**

Patroni is the HA manager that runs as a sidecar in each PostgreSQL pod. It handles:

| Patroni Responsibility | How It Works |
|----------------------|--------------|
| **Leader election** | Uses Kubernetes endpoints as DCS (Distributed Configuration Store) |
| **Health checks** | Continuously checks PostgreSQL process health |
| **Automatic failover** | If primary dies, promotes the healthiest replica within ~30 seconds |
| **Replication slots** | Manages physical replication slots for WAL streaming |
| **Configuration** | Dynamic configuration changes without pod restart |

**Our Real Configuration (CI Environment):**

```yaml
# From environments/ci/postgres-cluster/values.yaml
cluster:
  name: confirmation-pgdatabase
  image: 833618288067.dkr.ecr.us-east-1.amazonaws.com/a207804-ue1-op-pgo:ubi8-16.4-2
  instances:
    - name: instance-1
      replicas: 1
      instanceType: r5.4xlarge
      resources:
        requests: { memory: "32Gi", cpu: "2" }
        limits:   { memory: "64Gi", cpu: "4" }
      storage: { size: 200Gi, class: plexus-gp2 }
    - name: instance-2
      replicas: 1
      instanceType: r5.4xlarge
      storage: { size: 200Gi, class: plexus-gp2 }
  postgresVersion: 16
  port: 5432
```

**Non-Prod vs Production Differences:**

| Aspect | Non-Prod (CI/Demo/QA) | Production |
|--------|----------------------|------------|
| Cluster name | `confirmation-pgdatabase` | `confirmation-pgdb-av-common` (split by domain) |
| Namespace | `207804-postgres-ci` | `207804-postgres-prod` |
| Replicas | 2 instances × 1 replica | 2 replicas per instance |
| Storage | 200Gi | 600Gi |
| Resources | 32Gi/2CPU req, 64Gi/4CPU limit | 64Gi/8CPU req, 128Gi/16CPU limit |
| TLS | Disabled | Enabled (custom TLS + replication TLS) |
| WAL level | `logical` (Fivetran needs it) | `replica` (streaming only, no CDC in prod) |
| Max replication slots | 20 | 5 |
| WAL retention | `max_slot_wal_keep_size: 15GB` | `wal_keep_size: 4GB` |
| Prod sharding | Single cluster | 4 clusters: av-common, av-core, av-lmd, av-record |

**Why Production Uses 4 Separate Clusters:**

> "In production, we split PostgreSQL into domain-aligned clusters — `av-common` (shared services like pricing, forms, selfreg), `av-core` (nucleus, Orleans), `av-lmd` (LMD/GraphQL), and `av-record` (record silo). This gives us:
> - **Blast radius isolation**: A runaway query in pricing doesn't kill the nucleus database
> - **Independent scaling**: Core cluster can have more resources without over-provisioning common
> - **Independent maintenance**: We can upgrade or restart av-record without touching av-common
> - **Compliance**: Some data residency requirements need physical separation"

---

### 8.3 The PostgresCluster CRD — What the Operator Actually Creates

When we apply a `PostgresCluster` CRD, the Crunchy operator creates ~15 Kubernetes resources automatically:

```yaml
# From charts/postgres-cluster/templates/cluster.yaml
apiVersion: postgres-operator.crunchydata.com/v1beta1
kind: PostgresCluster
metadata:
  name: {{ .Values.cluster.name }}-{{ .Values.env }}
  namespace: {{ .Values.namespace }}
  annotations:
    sidecar.istio.io/inject: "false"  # PostgreSQL bypasses Istio mesh
```

**What the Operator Creates From This One CRD:**

| Resource | Name Pattern | Purpose |
|----------|-------------|---------|
| **StatefulSet** | `confirmation-pgdatabase-ci-instance-1` | Primary PostgreSQL pod |
| **StatefulSet** | `confirmation-pgdatabase-ci-instance-2` | Replica PostgreSQL pod |
| **StatefulSet** | `confirmation-pgdatabase-ci-repo-host` | pgBackRest dedicated backup pod |
| **Service** | `confirmation-pgdatabase-ci-primary` | Points to current primary (Patroni updates this) |
| **Service** | `confirmation-pgdatabase-ci-replicas` | Load-balanced across replicas |
| **PVC** | `confirmation-pgdatabase-ci-instance-1-xxxx` | 200Gi data volume per instance |
| **PVC** | `confirmation-pgdatabase-ci-repo-host-xxxx` | 200Gi pgBackRest repository |
| **Secret** | `confirmation-pgdatabase-ci-pguser-cfm-pricing-user-ci` | Per-database user credentials |
| **ConfigMap** | `confirmation-pgdatabase-ci-config` | postgresql.conf, pg_hba.conf |
| **ConfigMap** | `confirmation-pgdatabase-ci-patroni` | Patroni DCS configuration |

**Key Design Decision — Istio Bypass:**

> "PostgreSQL pods have `sidecar.istio.io/inject: false`. Database traffic uses its own TLS (native PostgreSQL SSL in prod) instead of Istio mTLS. Why? Because database connections are long-lived (pooled), and Istio's sidecar would add latency to every query. Also, PostgreSQL's wire protocol doesn't work well with Envoy's L7 proxy — it's a binary protocol, not HTTP."

---

### 8.4 PostgreSQL Tuning Parameters — What We Set and Why

```yaml
# From our values.yaml
parameters:
  - name: max_connections
    value: 500
  - name: shared_buffers
    value: '16GB'
  - name: work_mem
    value: '256MB'
  - name: log_min_duration_statement
    value: 1000           # Log queries slower than 1 second
  - name: log_statement
    value: 'ddl'          # Log CREATE/ALTER/DROP only (not every SELECT)
  - name: archive_timeout
    value: '120'          # Force WAL archive every 2 minutes
  - name: wal_level
    value: 'logical'      # For Fivetran CDC (non-prod only)
  - name: max_replication_slots
    value: '20'           # 5 Fivetran slots + headroom
  - name: max_wal_senders
    value: '20'           # WAL streaming connections
  - name: hot_standby_feedback
    value: 'on'           # Replica tells primary about long queries
  - name: max_slot_wal_keep_size
    value: '15GB'         # Safety cap on WAL retention per slot
```

**Interview Answer — "How do you tune shared_buffers?":**

> "The rule of thumb is 25% of total RAM, but it depends on the workload. Our r5.4xlarge nodes have 128GB RAM, and we set `shared_buffers: 16GB` — that's about 12.5%. Why not 32GB?
>
> Because PostgreSQL also relies on the OS page cache. If you set shared_buffers too high, you're double-caching data (once in shared_buffers, once in OS cache). 16GB is the sweet spot for our mixed workload — frequent reads (audit confirmations lookup) and write bursts (batch imports).
>
> The more impactful tuning for us was `work_mem: 256MB`. Our reporting queries do large sorts and hash joins. With the default 4MB, PostgreSQL was spilling to disk constantly. 256MB eliminated most disk sorts. But you have to be careful — `work_mem` is *per-operation*, not per-connection. A complex query with 5 sort operations uses 5 × 256MB. With 500 max_connections, the theoretical max is enormous, so we also use PgBouncer to limit actual concurrent connections."

**Interview Answer — "What's hot_standby_feedback and why is it important?":**

> "When a replica runs a long query, the primary might vacuum rows that the replica still needs — causing the replica to cancel the query with a `canceling statement due to conflict with recovery` error. `hot_standby_feedback: on` tells the primary about the replica's oldest running transaction, so the primary delays vacuuming those rows. The trade-off is potential table bloat on the primary if the replica runs very long queries."

---

### 8.5 pgBackRest — Backup Strategy

pgBackRest is our PostgreSQL backup tool. It runs as a dedicated pod (repo-host) managed by the Crunchy operator.

**Backup Types:**

| Type | What It Does | Our Schedule | Size |
|------|-------------|-------------|------|
| **Full** | Complete copy of all data files | Daily at 2:30 AM IST (`0 21 * * *` UTC) | ~50-80GB |
| **Differential** | Only files changed since last full | Every 6 hours (`0 */6 * * *`) | ~5-15GB |
| **Incremental** | Only files changed since last diff/incr | Not used (differential sufficient) | Smallest |

**Retention Policy:**

```yaml
# From values.yaml
global:
  repo1-retention-full: "1"    # Keep 1 full backup
  repo1-retention-diff: "4"    # Keep 4 differential backups per full
```

**Dual-Destination Backup Architecture:**

```
PostgreSQL Pod ──WAL──▶ pgBackRest Repo Pod (200Gi PVC)
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
           S3 Outposts              S3 Cloud
      (same data center)     (a207804-cn-database-backup-postgres)
      Disaster recovery       Cross-region accessibility
      CronJob sync: */4h      pg_dump CronJob: daily
```

**Why Two Destinations?**

> "pgBackRest writes to a local PVC first (200Gi plexus-gp2). Then we have two sync mechanisms:
>
> 1. **Backup Sync Job** — A CronJob (`backup-sync-job.yaml`) runs every 4 hours, copies pgBackRest archives from the repo-host pod to S3 Outposts using `kubectl cp` + `aws s3 cp`. This is our disaster recovery copy — if the entire EKS cluster dies, we can restore from S3.
>
> 2. **Custom Backup Job** — A separate CronJob (`custom-backup-cronjob.yaml`) runs `pg_dump` in parallel (5 databases at a time) and pushes to both S3 Outposts AND S3 Cloud. The cloud copy goes to `a207804-cn-database-backup-postgres` with environment-prefixed paths (`ci/`, `demo/`, `qa/`). This is for the db-ops portal — developers can download database backups through a presigned URL."

**Backup Sync Job Details (backup-sync-job.yaml):**

```yaml
# CronJob that syncs pgBackRest repo to S3 Outposts
apiVersion: batch/v1
kind: CronJob
metadata:
  name: confirmation-pgdatabase-ci-backup-sync-job
  namespace: 207804-postgres-ci
spec:
  schedule: "55 */4 * * *"    # Every 4 hours at :55
  # Process:
  # 1. Lock mechanism to prevent concurrent syncs
  # 2. kubectl cp from repo-host pod to sync PVC
  # 3. Organize by full backup interval (YYYYMMDD-HHMMSSF)
  # 4. aws s3 cp to S3 Outposts with multipart (1024MB threshold, 16MB chunks)
  # 5. Cleanup workspace after completion
```

**Custom pg_dump Job Details:**

```yaml
customBackup:
  enabled: true
  schedule: "0 16 * * *"  # Daily at 11:00 AM EST
  storage: "200Gi"
  databases:    # 15 databases backed up in parallel (5 concurrent)
    - cfm_pricing_ci
    - cfm_forms_ci
    - cfm_selfreg_ci
    - cfm_core_ci
    - cfm_core_rel_ci
    - cfm_record_ci
    # ... 15 databases total
```

**Interview Answer — "Explain your PostgreSQL backup strategy":**

> "We use a three-layer backup approach:
>
> **Layer 1 — Continuous WAL archiving**: pgBackRest continuously archives WAL segments. This gives us point-in-time recovery (PITR) — we can restore to any second within the retention window.
>
> **Layer 2 — Scheduled full + differential**: Daily full backup at 2:30 AM IST, plus differential every 6 hours. These are stored on a dedicated 200Gi PVC and synced to S3 Outposts every 4 hours. This is our disaster recovery path.
>
> **Layer 3 — pg_dump to S3 Cloud**: Daily logical backups of all 15 databases using parallel pg_dump (directory format, 5 jobs). These go to both S3 Outposts and S3 Cloud. The cloud copy powers our db-ops portal where developers can download backups via presigned URLs.
>
> The key insight is: pgBackRest gives us fast, physical-level recovery (restore the whole cluster), while pg_dump gives us logical, portable backups (restore a single database, or import into a different environment). We need both."

---

### 8.6 Fivetran Logical Replication — The Patroni Failover Problem

**The Problem:**

Fivetran uses PostgreSQL's logical replication to stream changes from our operational databases to the data warehouse. This requires `wal_level=logical` and logical replication slots. The problem? **When Patroni fails over to a new primary, logical replication slots are lost.**

Physical replication slots (used by Patroni for streaming replication) survive failover because Patroni manages them. But logical replication slots (used by Fivetran) are NOT managed by Patroni by default — they exist only on the primary and don't get recreated on the new primary.

**The Solution — Two-Layer Protection:**

**Layer 1: Patroni Managed Slots**

```yaml
# From values.yaml — tells Patroni to recreate these slots on failover
patroni:
  useSlots: true
  slots:
    fivetran_core_slot:
      type: logical
      database: cfm_core_ci
      plugin: pgoutput
    fivetran_core_rel_slot:
      type: logical
      database: cfm_core_rel_ci
      plugin: pgoutput
    fivetran_forms_slot:
      type: logical
      database: cfm_forms_ci
      plugin: pgoutput
    fivetran_pricing_slot:
      type: logical
      database: cfm_pricing_ci
      plugin: pgoutput
    fivetran_record_slot:
      type: logical
      database: cfm_record_ci
      plugin: pgoutput
```

By declaring slots in Patroni's configuration, Patroni will recreate them on the new primary after failover. But there's a catch — the slot is recreated *empty* (no LSN position), so Fivetran doesn't know where it left off.

**Layer 2: Fivetran Slot Manager CronJob**

```bash
# From fivetran-slot-manager.yaml — runs every 5 minutes
# 1. Connect to primary (skip if replica)
# 2. Check each slot exists and has valid wal_status
# 3. If slot missing → create with pg_create_logical_replication_slot()
# 4. If slot has 'lost' wal_status → drop and recreate
# 5. Fetch Fivetran API credentials from AWS Secrets Manager
# 6. List Fivetran connectors targeting our database
# 7. Trigger historical re-sync for affected connectors
```

**The Full Failover Timeline:**

```
T+0s:   Primary (instance-1) crashes
T+30s:  Patroni detects failure, promotes instance-2 to primary
T+31s:  Patroni recreates logical replication slots (empty)
T+60s:  Applications reconnect (primary Service updated)
T+5min: Fivetran Slot Manager CronJob runs:
        → Detects slots were recreated (no LSN match)
        → Calls Fivetran API to trigger historical re-sync
        → Fivetran starts full re-sync from slot position
T+30min: Fivetran re-sync completes, data warehouse current
```

**Interview Answer — "How did you solve the Fivetran replication slot problem?":**

> "This was one of our trickiest operational challenges. Fivetran uses PostgreSQL logical replication slots to stream CDC changes to our data warehouse. When Patroni does an automatic failover — say the primary pod gets evicted — the logical replication slots are lost because they only exist on the old primary.
>
> We built a two-layer solution:
>
> First, we configured Patroni to manage the slots by declaring them in the dynamic configuration. Patroni recreates them on the new primary after failover. But the recreated slot starts from the current WAL position, not where Fivetran left off — so Fivetran's position is stale.
>
> Second, we built a Fivetran Slot Manager — a CronJob that runs every 5 minutes. It connects to the primary, checks each slot's WAL status, and if a slot was recently recreated (detected by checking if the WAL status is 'lost' or the slot was just created), it calls the Fivetran REST API to trigger a historical re-sync for affected connectors.
>
> The slot manager also handles edge cases: it fetches Fivetran API credentials from AWS Secrets Manager using IRSA, filters connectors by target database, and skips re-sync if one is already in progress. The whole thing is idempotent — running it on an already-healthy cluster is a no-op."

---

### 8.7 Database Secrets Management

Every database user's credentials are managed through a chain:

```
AWS Secrets Manager                  ExternalSecret                     K8s Secret
(a207804-ue1-op-pricing-be-ci-db-sm) ──sync──▶ (ExternalSecret CRD) ──creates──▶ (confirmation-pgdatabase-ci-pguser-cfm-pricing-user-ci)
                                                                            │
                                                                    .NET Service reads
                                                                    connection string
```

**Naming Conventions:**

| Entity | Pattern | Example |
|--------|---------|---------|
| AWS Secret | `a207804-ue1-op-{service}-{env}-db-sm` | `a207804-ue1-op-pricing-be-ci-db-sm` |
| K8s Secret | `{cluster}-pguser-{username}` | `confirmation-pgdatabase-ci-pguser-cfm-pricing-user-ci` |
| Database | `cfm_{service}_{env}` | `cfm_pricing_ci` |
| DB User | `cfm-{service}-user-{env}` | `cfm-pricing-user-ci` |

**Our CI Cluster Has 17 Database/User Pairs:**

| Database | Service | AWS Secret |
|----------|---------|------------|
| `cfm_pricing_ci` | Pricing BE | `a207804-ue1-op-pricing-be-ci-db-sm` |
| `cfm_forms_ci` | Forms BE | `a207804-ue1-op-forms-be-ci-db-sm` |
| `cfm_selfreg_ci` | SelfReg BE | `a207804-ue1-op-selfreg-be-ci-db-sm` |
| `cfm_core_ci` | Nucleus Orleans | `a207804-ue1-op-nucleus-orl-be-ci-db-sm` |
| `cfm_core_rel_ci` | Nucleus Relay | `a207804-ue1-op-nucleus-rel-be-ci-db-sm` |
| `cfm_record_ci` | Record Silo | `a207804-ue1-op-record-silo-be-ci-db-sm` |
| `cfm_authorization_ci` | Authorizations | `a207804-ue1-op-authorizations-be-ci-db-sm` |
| `cfm_lmd_ci` | LMD GraphQL | `a207804-ue1-op-lmd-gql-be-ci-db-sm` |
| `cfm_datalake_ci` | Datalake | `a207804-ue1-op-datalake-ci-db-sm` |
| ... | +8 more databases | |

**Why One Database Per Service?**

> "Each microservice gets its own database — not just a schema, a full database. This enforces hard boundaries. A bug in the pricing service can't accidentally query the forms database. It also lets us set per-database connection limits, backup independently, and grant minimal IAM permissions — the pricing service's Secrets Manager secret only contains credentials for `cfm_pricing_ci`."

---

### 8.8 The db-ops API — Cross-Namespace Database Diagnostics

I built a FastAPI service (`audit-devops-db-ops`) that gives our team safe, audited access to PostgreSQL across all environments through the DevOps portal.

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/database/query` | POST | Execute SELECT queries (read-only) |
| `/api/v1/database/update` | POST | Execute UPDATE/INSERT/DELETE |
| `/api/v1/database/long-running-queries` | POST | Find queries running > N minutes |
| `/api/v1/database/locks` | POST | Show current database locks |
| `/api/v1/database/connections` | POST | Active connection details |
| `/api/v1/database/stats` | POST | Database size, connection count, table count |
| `/api/v1/database/table-sizes` | POST | Individual table sizes |
| `/api/v1/database/kill-query` | POST | Terminate a query by PID |
| `/api/v1/s3-backup/generate-presigned-url` | POST | Download backup via S3 presigned URL (5h expiry) |

**How It Connects Cross-Namespace:**

```python
# The service reads credentials from K8s secrets in the POSTGRES namespace
# Secret name pattern: {cluster_name}-pguser-{username}
# It uses the K8s API to read secrets from 207804-postgres-{env} namespace
# Then connects via the primary Service:
#   confirmation-pgdatabase-{env}-primary.207804-postgres-{env}.svc.cluster.local:5432
```

**Why This Matters for Operations:**

> "Before db-ops, debugging a database issue meant: SSH into a pod, install psql, find the connection string, run the query, hope you don't accidentally run it against prod. Now our team goes to the portal, selects the environment and database from a dropdown, and runs diagnostic queries. Every query is logged and audited. The kill-query endpoint has saved us during incidents — when a runaway query locks the pricing table, we can kill it in seconds from the portal instead of scrambling for kubectl access."

---

### 8.9 Production TLS Configuration

Production PostgreSQL clusters use their own TLS certificates (not Istio mTLS):

```yaml
# From environments/prod/postgres-cluster-av-common/values.yaml
tls:
  enabled: true
customTLSSecret:
  name: confirmation-pgdb-av-common-prod-tls-secret
customReplicationTLSSecret:
  name: confirmation-pgdb-av-common-prod-repl-tls-secret
```

**Two Separate TLS Certificates:**

| Certificate | Purpose | Scope |
|-------------|---------|-------|
| `customTLSSecret` | Client → PostgreSQL connections | Application services connecting to the database |
| `customReplicationTLSSecret` | Primary → Replica WAL streaming | Inter-node replication traffic |

**Why Separate Certificates?**

> "Client TLS and replication TLS have different trust requirements. Client certificates are issued by our corporate CA — any service with a valid certificate can connect. Replication certificates use a cluster-internal CA — only PostgreSQL nodes can authenticate as replication peers. If a client certificate is compromised, the attacker can read data but can't impersonate a replica and inject fake WAL records."

---

### 8.10 Common PostgreSQL Operational Tasks

**Task: Expand PVC Storage (200Gi → 600Gi)**

```bash
# Our StorageClass (plexus-gp2) has allowVolumeExpansion: true
# Edit the PVC directly — Crunchy operator handles the rest
kubectl edit pvc confirmation-pgdatabase-ci-instance-1-xxxx -n 207804-postgres-ci
# Change storage: 200Gi → 600Gi
# EBS volume expands online — no downtime
# IMPORTANT: You can only expand, NEVER shrink
```

**Task: Check Replication Lag**

```sql
-- On the primary
SELECT client_addr, state, sent_lsn, write_lsn, flush_lsn, replay_lsn,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes
FROM pg_stat_replication;
```

**Task: Find and Kill Long-Running Queries**

```sql
-- Find queries running more than 5 minutes
SELECT pid, now() - pg_stat_activity.query_start AS duration, query, state
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 minutes'
  AND state != 'idle';

-- Kill a specific query (graceful)
SELECT pg_cancel_backend(12345);

-- Force kill (if cancel doesn't work)
SELECT pg_terminate_backend(12345);
```

**Task: Check Table Bloat**

```sql
-- Estimate dead tuples (need vacuum)
SELECT relname, n_live_tup, n_dead_tup,
       ROUND(n_dead_tup::numeric / NULLIF(n_live_tup, 0) * 100, 2) AS dead_pct
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;
```

**Task: Manual pgBackRest Backup**

```bash
# Exec into the repo-host pod
kubectl exec -it confirmation-pgdatabase-ci-repo-host-0 -n 207804-postgres-ci -- bash

# Run a full backup
pgbackrest --stanza=db --type=full backup

# Check backup info
pgbackrest --stanza=db info
```

---

### 8.11 Point-in-Time Recovery (PITR)

PITR lets you restore the database to any specific moment — critical for "undo" scenarios like accidental data deletion.

**How PITR Works with pgBackRest:**

```
Full Backup          Diff Backup          Diff Backup         Current
(2:30 AM)           (8:30 AM)            (2:30 PM)           (3:45 PM)
   │                    │                    │                    │
   ▼                    ▼                    ▼                    ▼
   ████████████████████████████████████████████████████████████████
   └──────── Continuous WAL archiving fills the gaps ────────────┘
                                                    ▲
                                              Restore to here
                                              (e.g., 1:00 PM)
```

**Recovery Process:**

1. pgBackRest restores the closest full backup before target time
2. Applies the differential backup closest to target time
3. Replays WAL records up to the exact target timestamp
4. PostgreSQL opens in recovery mode, then promotes to primary

**Interview Answer — "A developer accidentally deleted production data. How do you recover?":**

> "First, I'd assess the blast radius — which table, how many rows, when did it happen. Then:
>
> 1. **Don't panic, don't restart** — the WAL still has the delete operation, but pgBackRest has the data before it
> 2. **Check the exact timestamp** from application logs or `pg_stat_activity` history
> 3. **Spin up a recovery instance** — NOT restore in-place. I'd use pgBackRest to restore to a separate PostgreSQL instance with `--target-time='2026-03-10 14:30:00'` and `--target-action=promote`
> 4. **Verify the recovered data** — connect to the recovery instance, confirm the rows exist
> 5. **Extract and re-insert** — pg_dump the affected table from recovery, pg_restore into production
> 6. **Post-mortem** — add guardrails: the db-ops portal should require confirmation for DELETE operations, and we should consider enabling `log_statement=mod` temporarily to catch this earlier"

---

### 8.12 Data Warehouse — Citus (Distributed PostgreSQL)

For analytics and reporting, we run a separate **Citus** cluster (distributed PostgreSQL):

```
┌──────────────────────┐
│ Citus Coordinator    │ ← Receives queries, routes to workers
│ (postgres-dwh)       │
├──────────────────────┤
│ Worker-101           │ ← Holds distributed table shards
│ Worker-102           │ ← Holds distributed table shards
└──────────────────────┘
```

**How Data Flows:**

```
.NET Services → PostgreSQL (operational) → Fivetran CDC → Data Warehouse (Citus)
                                                              │
                                                    dbt Transformations
                                                    (HookDeck → GitHub Actions)
                                                              │
                                                    Power BI Reports
```

**Why Citus Instead of Regular PostgreSQL?**

> "Our analytics queries scan millions of rows across months of confirmation data. A single PostgreSQL instance would take minutes. Citus distributes the data across worker nodes and parallelizes the query — each worker scans its shard, the coordinator aggregates results. We went from 5-minute reports to sub-second responses for most dashboard queries."

---

### 8.13 Interview Scenario Questions

**Q: "Your PostgreSQL primary pod got OOMKilled. What happens and how do you investigate?"**

> "When the primary pod gets OOMKilled:
>
> 1. **Patroni detects the failure** within ~30 seconds and promotes the replica to primary
> 2. **The primary Service** (`confirmation-pgdatabase-ci-primary`) is updated to point to the new primary
> 3. **Applications reconnect** — .NET services use the Service DNS, so they automatically connect to the new primary
> 4. **The old primary restarts** and rejoins as a replica (Patroni handles this)
>
> To investigate the OOM:
> - `kubectl describe pod` — check the `lastState` for OOMKilled and the memory limit
> - Check `pg_stat_activity` on the new primary — was there a connection spike?
> - Check `work_mem` usage — a complex query with many sort/hash operations can consume `work_mem × operations × connections`
> - Check for connection leaks — `SELECT count(*) FROM pg_stat_activity GROUP BY state` — are there hundreds of idle connections?
> - Solution: either increase the memory limit, tune `work_mem` down, or fix the connection leak in the application"

**Q: "Fivetran shows 'connector broken' after a weekend. How do you troubleshoot?"**

> "This is usually a replication slot issue. My troubleshooting steps:
>
> 1. **Check the slot manager logs**: `kubectl logs -l app=fivetran-slot-manager -n 207804-postgres-ci` — did it detect and fix the slot?
> 2. **Check slot status directly**:
>    ```sql
>    SELECT slot_name, active, restart_lsn, confirmed_flush_lsn, wal_status
>    FROM pg_replication_slots WHERE slot_type = 'logical';
>    ```
>    If `wal_status = 'lost'`, the WAL Fivetran needs has been recycled — the slot manager should recreate it
> 3. **Check `max_slot_wal_keep_size`** — we set it to 15GB. If Fivetran was down for the weekend and WAL accumulated beyond 15GB, PostgreSQL drops the oldest WAL, making the slot 'lost'
> 4. **Fix**: The slot manager handles this automatically — it drops the lost slot, recreates it, and triggers a Fivetran historical re-sync via the API. If the slot manager isn't running, I'd do it manually:
>    ```sql
>    SELECT pg_drop_replication_slot('fivetran_core_slot');
>    SELECT pg_create_logical_replication_slot('fivetran_core_slot', 'pgoutput');
>    ```
>    Then trigger re-sync in the Fivetran dashboard or via API."

**Q: "How would you migrate from PostgreSQL 15 to 16 with zero downtime?"**

> "The Crunchy operator supports this with `PGUpgrade` CRD:
>
> 1. **Test in non-prod first** — run the upgrade in CI, verify all .NET services work with PG 16
> 2. **Take a fresh backup** — full pgBackRest backup before any upgrade attempt
> 3. **Update the image and version in values.yaml** — change `postgresVersion: 15` to `16` and update the image tag
> 4. **Apply PGUpgrade CRD** — the operator creates new PG 16 pods, runs `pg_upgrade --link` (hard links, fast), switches traffic
> 5. **Run ANALYZE** — after upgrade, statistics are stale. Run `ANALYZE` on all databases to rebuild planner stats
> 6. **Monitor for 24 hours** — watch query latency, connection errors, replication lag
> 7. **Clean up** — remove old PG 15 data volumes after confirming stability
>
> The key is the `--link` mode — it uses hard links instead of copying data files, so the upgrade itself takes minutes, not hours. The downtime window is just the time to stop the old primary, run pg_upgrade, and start the new primary — typically under 5 minutes."

**Q: "Your database storage is at 85%. What do you do?"**

> "Immediate actions:
>
> 1. **Check table bloat**: `SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10` — if dead tuples are high, run `VACUUM FULL` on the worst offenders (note: VACUUM FULL locks the table, schedule during low traffic)
>
> 2. **Check for orphaned data**: Old audit confirmations that can be archived or deleted
>
> 3. **Expand the PVC**: Since our StorageClass has `allowVolumeExpansion: true`, I can edit the PVC from 200Gi to 400Gi — EBS expands online, no downtime. In production we already went from 200Gi to 600Gi this way.
>
> 4. **Long-term**: If the growth pattern is consistent, set up monitoring alerts at 70% and 85%, and plan for either larger PVCs or partitioning large tables by date."

**Q: "How do you ensure database credentials are secure in Kubernetes?"**

> "We use a full secrets chain:
>
> 1. **Credentials are born in AWS Secrets Manager** — never hardcoded, never in git
> 2. **ExternalSecrets Operator** syncs them to K8s Secrets — the ESO checks Secrets Manager every 15 minutes for changes
> 3. **K8s Secrets are mounted as environment variables** in the .NET service pods
> 4. **Network isolation** — PostgreSQL runs in its own namespace (`207804-postgres-ci`), and Istio AuthorizationPolicy restricts which namespaces can connect
> 5. **Per-service credentials** — each service has its own database user with access only to its own database. The pricing service literally cannot query the forms database.
> 6. **No wildcard pg_hba** in production — we restrict source IPs to the pod CIDR ranges
>
> The naming convention makes auditing easy: `a207804-ue1-op-pricing-be-ci-db-sm` tells you the asset (a207804), region (ue1), Outpost (op), service (pricing-be), environment (ci), and that it's a database secret (db-sm)."

**Q: "Explain the difference between physical and logical replication and when you'd use each"**

> "Physical replication (streaming replication) copies WAL records byte-by-byte to the replica. The replica is an exact binary copy of the primary — same databases, same tables, same indexes. It's fast and simple. We use it for HA — our Patroni setup streams WAL from primary to replica for automatic failover.
>
> Logical replication decodes the WAL into logical changes (INSERT row X, UPDATE row Y, DELETE row Z). It's more flexible — you can replicate specific tables, specific databases, or even transform data during replication. We use it for Fivetran CDC — Fivetran reads the logical changes through the `pgoutput` plugin to stream data to the warehouse.
>
> The trade-offs:
> - Physical: faster, lower overhead, but all-or-nothing (entire cluster)
> - Logical: flexible, selective replication, but higher WAL overhead (`wal_level=logical` generates more WAL than `replica`)
>
> That's why we use `wal_level=logical` only in non-prod (where Fivetran runs) and `wal_level=replica` in production — production doesn't need CDC, so we avoid the extra WAL overhead."

---
