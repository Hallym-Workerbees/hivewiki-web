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

## Database schema

- If a requested change would require a schema change, call it out in the final summary instead of making it.

## Quality checks

- Keep changes compatible with pre-commit: uv-lock, Ruff, djLint, gitleaks, Commitizen.
- Run `pre-commit run --all-files` before finalizing changes when practical.

## Deployment awareness

- This repo contains application code only.
- GitOps and infrastructure are managed in separate repositories.
- Mention required follow-up when changes affect env vars, migrations, static assets, sessions, caching, or startup behavior.

## General

- Make the smallest change that fully solves the problem.
- Do not modify unrelated files.
- Do not introduce secrets or hardcoded environment-specific values.
