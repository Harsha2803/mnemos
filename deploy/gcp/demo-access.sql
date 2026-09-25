-- Grants the demo user what the scripted walkthrough (docs/Demo.md) needs.
-- Idempotent; run as the owning superuser after `mnemosctl bootstrap` and after
-- analyst@mnemos.local has signed in once (sign-in provisions the user row):
--
--   deploy/gcp/compose.sh exec -T postgres psql -U mnemos -d mnemos -v ON_ERROR_STOP=1 \
--     < deploy/gcp/demo-access.sql
--
-- Why this exists: just-in-time OIDC provisioning grants identity, never authority
-- (features/identity/application/tokens.py), and nothing maps Keycloak realm roles
-- to local roles yet, so a freshly deployed org's analyst can sign in and do nothing
-- with tools. There is no `mnemosctl` command to bind a role either (TRACKER §6).
--
-- `demo` = the `analyst` system role plus `tool:manage`, because the walkthrough has
-- the same user register the demo MCP server before granting and running a tool.

INSERT INTO role (org_id, slug, name, permissions)
SELECT o.id, 'demo', 'Demo walkthrough',
       (SELECT r.permissions || '["tool:manage"]'::jsonb
          FROM role r WHERE r.org_id = o.id AND r.slug = 'analyst')
  FROM org o WHERE o.slug = 'mnemos'
ON CONFLICT (org_id, slug) DO UPDATE SET permissions = EXCLUDED.permissions, updated_at = now();

INSERT INTO role_binding (org_id, user_id, role_id)
SELECT u.org_id, u.id, r.id
  FROM app_user u
  JOIN org o ON o.id = u.org_id AND o.slug = 'mnemos'
  JOIN role r ON r.org_id = u.org_id AND r.slug IN ('analyst', 'demo')
 WHERE u.email = 'analyst@mnemos.local'
ON CONFLICT DO NOTHING;

SELECT u.email, r.slug
  FROM role_binding b JOIN app_user u ON u.id = b.user_id JOIN role r ON r.id = b.role_id
 ORDER BY 1, 2;
