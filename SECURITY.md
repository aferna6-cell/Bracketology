# Security Policy

## Threat model

Bracketology is a public-facing read-only web application that fetches data
from ESPN and displays computed projections. The primary risks are:

- **Abuse of external API calls** (rate limiting/caching required).
- **Resource exhaustion** via repeated update/what-if requests.
- **Input validation issues** in JSON and query parameters.
- **Sensitive information in logs** (avoid leaking secrets or raw stack traces).

## Security assumptions

- **Authentication/authorization:** No user accounts or auth; all endpoints are public.
- **API keys/secrets:** None are required. Do not log or commit secrets.
- **Rate limiting:** In-memory rate limiting is enabled for key endpoints; deploy
  behind a reverse proxy/WAF for stronger protections.
- **Data storage:** SQLite database stored locally; ensure filesystem permissions
  restrict access in production environments.
- **Logging:** Logs are informational and should not include secrets or PII.

## Reporting a vulnerability

Please open a private security report or contact the maintainer with a detailed
description, steps to reproduce, and potential impact.
