# AGENTS.md

## Stack

- Django
- htmx
- Tailwind CSS
- PostgreSQL
- Valkey (Redis-compatible) for sessions and caching

## Architecture

- Prefer server-rendered Django templates.
- Use htmx for partial updates.
- Avoid SPA-style or JS-heavy solutions unless explicitly requested.
- Prefer HTML responses over JSON APIs for htmx-only features.

## Coding guidelines

- Follow existing project patterns and structure.
- Keep business logic out of templates.
- Use Django forms for validation.
- Keep views thin; move larger logic into services, forms, or model methods.
- Reuse existing Tailwind patterns and keep class lists readable.
- Avoid unnecessary dependencies and unrelated refactors.
- Use structured JSON logging via the existing logging setup; do not add `print()` debugging.
- When adding application logs, prefer `logging.getLogger(__name__)` and keep logs compatible with the JSON stdout formatter.
- Preserve request log context fields such as `request_id`, `method`, `path`, `status_code`, `duration_ms`, `user_id`, and `remote_addr`.

## htmx

- Full-page request -> full template
- htmx request -> partial template (HTML response, not JSON)
- Validation errors -> re-render the relevant form partial
- Preserve CSRF correctness for mutating requests

## Data and state

- PostgreSQL is the source of truth.
- Valkey (Redis-compatible) is used for sessions and caching.
- Do not treat cache or sessions as durable business storage.
- Do not rely on in-process memory for shared state.
- Datetimes should remain UTC in the database. User-facing rendering should use the browser timezone captured in session storage.
- The browser timezone is stored in session key `django_timezone` and must survive login/logout flows that call `session.flush()`.

## Database schema

- If a requested change would require a schema change, call it out in the final summary instead of making it.

## Quality checks

- Keep changes compatible with pre-commit: uv-lock, Ruff, djLint, gitleaks, Commitizen.
- Run `pre-commit run --all-files` before finalizing changes when practical.
- When local tooling depends on the project devshell, prefer `nix develop --command ...` for `uv`, Django management commands, tests, and pre-commit.

## Deployment awareness

- This repo contains application code only.
- GitOps and infrastructure are managed in separate repositories.
- Mention required follow-up when changes affect env vars, migrations, static assets, sessions, caching, or startup behavior.

## General

- Make the smallest change that fully solves the problem.
- Do not modify unrelated files.
- Do not introduce secrets or hardcoded environment-specific values.
- If a template renders timezone-sensitive timestamps, use the existing `timezone-sensitive` UI pattern so incorrect server-time first paint is hidden until browser timezone sync completes.
