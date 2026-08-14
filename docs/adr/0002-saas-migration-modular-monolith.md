# ADR-0002: Migrate to a locally runnable multi-tenant SaaS with a FastAPI BFF

- Status: Accepted
- Date: 2026-08-14

## Context

The current checkout is a local-first FastAPI/Jinja2 application with embedded
Qdrant and no organization, billing, public-widget, or tenant boundary. The
approved product target adds company workspaces, a premium React UI, billing,
and an embeddable chatbot while remaining fully testable on one local computer
before it is hosted.

## Decision

Use a modular monolith for the first stage: a React/TypeScript/Tailwind/shadcn
frontend, a FastAPI BFF retaining the LangGraph RAG core, a bounded ingestion
worker, Supabase for authentication and relational organization data, Qdrant
collections isolated per workspace, and Stripe test-mode subscriptions.

FastAPI is the sole trusted BFF for the SaaS frontend and public widget. It
enforces Supabase identity/membership/role checks, billing entitlements,
workspace-to-Qdrant-collection mapping, public-widget key and origin checks,
rate limits, error redaction, and streaming responses. Clients do not call
privileged Qdrant, Stripe, or Supabase operations directly.

Launch roles are `owner`, `admin`, and `member`; only owners and admins may
upload, delete, or re-index company knowledge. Public widgets use a
workspace/chatbot-specific public key, server-side approved-origin allowlist,
and rate limits. Existing local data is not automatically migrated.

## Alternatives considered

1. Full microservices from the start. Rejected because the local test
   environment would gain distributed deployment, authentication, observability,
   and failure complexity before demand proves an extraction is needed. Revisit
   when measured ingestion backlog, independent scaling, or operational
   ownership justifies a separate service.
2. Direct browser access to Supabase/Qdrant/Stripe. Rejected because it would
   split authorization and entitlement logic across clients and expose unsafe
   paths to tenant data or billing actions. Revisit only for narrowly scoped,
   policy-reviewed public reads.
3. One shared Qdrant collection with a `tenant_id` payload filter. Rejected by
   product decision in favor of clearer company deletion/export boundaries and
   enterprise isolation. Revisit if measured collection count or operational
   overhead becomes the limiting cost.

## Consequences

Local Compose must support the complete user flow with persistent data,
environment-based configuration, health checks, and documented deployment
configuration. Stripe uses test mode and webhooks are the entitlement source of
truth. The initial testable concurrency target is ten active users/requests,
including public-widget traffic; bounded overload must return sanitized `429`
or `503` responses rather than cross-tenant access, uncontrolled queue growth,
or process failure.

## Safety and rollback

Keep the current local app and its data untouched during the clean-start
migration. Feature flags or routing can retain the legacy path while the SaaS
path is incomplete. Rollback disables SaaS routes/widgets and preserves each
workspace's separate collection and relational records for later recovery; it
never bulk-deletes collections, documents, or Stripe customer data.
