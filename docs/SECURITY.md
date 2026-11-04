# Security

## Scope and ethical boundaries
CyberLead 360 is a **sales** tool. It performs **no** vulnerability scanning, port scanning,
credential collection, intrusive reconnaissance or testing of prospects. Lead scoring is
kept separate from security assessment, and the AI layer is blocked from asserting weaknesses.

## Threat model (summary)
| Asset / entry point | Threat | Mitigation | Residual risk |
|---|---|---|---|
| Database | SQL injection | ORM with bound parameters; LIKE wildcards escaped | Low |
| Forms & CSV | Malformed or hostile input | Pydantic schemas (`extra="forbid"`), size and row limits, encoding check, per-row errors | Low |
| CSV exports | Formula injection (`=cmd…`) in Excel | `neutralize_csv_formula` prefixes `= + - @ \t \r` with `'` | Low |
| UI rendering | XSS / markdown injection from stored text | Untrusted text rendered with `st.text`, dataframes or escaped markdown; `unsafe_allow_html` only for static CSS and enum-based badges; link buttons only for http(s) URLs | Low |
| Web retrieval | SSRF to internal services / cloud metadata | Scheme allow-list; ports 80/443; no credentials in URLs; **every** DNS answer must be public (private, loopback, link-local incl. 169.254.169.254, CGNAT, multicast, reserved, IPv4-mapped IPv6 blocked); manual redirects re-validated (max 3); domain restricted to the company's site by default; disabled by default | DNS rebinding between check and connect. Enforce egress filtering at the network layer in production |
| Web retrieval | Resource exhaustion, abuse | Timeouts, streamed 1 MB cap, HTML only, per-host rate limit, robots.txt, clear User-Agent | Low |
| LLM | Prompt injection via retrieved text | Facts must be human-approved; sanitized and delimited data block; system rules; output schema; risk-claim filter; human approval | Pattern filters can be bypassed. Human review stays mandatory |
| LLM | Data leakage to provider | Only company data and job titles are sent; names, e-mails and phones never; prompts not logged | Provider retention policies apply |
| Secrets | Key exposure | Env vars only, `SecretStr`, `.env` git-ignored, never stored in DB or shown in UI, log redaction | Operator responsibility |
| Logs | PII in logs | Redaction filter (e-mails, `sk-…` keys); audit details hold field names, not values | Low |
| Files | Path traversal on export | Strict name regex + resolved path must stay inside the export dir | Low |
| Web server | CSRF / cross-origin WebSocket | Streamlit XSRF protection and CORS enabled, bound to `localhost`; Docker publishes on 127.0.0.1 | No authentication (see below) |
| Container | Privilege escalation | Non-root user (uid 10001), `no-new-privileges`, slim base, locked deps | Low |
| Dependencies | Known CVEs | `uv.lock`; `pip-audit` and `bandit` in CI | Ongoing maintenance |

## Authentication and authorization (not implemented)
The demonstrator is **single-operator** and has **no login**. `OPERATOR_NAME` labels audit
events but proves nothing. **Do not deploy it to a shared network as is.** A multi-user
deployment needs:
* an identity provider (OIDC/SAML SSO) in front of the app, e.g. a reverse proxy such as
  oauth2-proxy, or a FastAPI backend with proper sessions;
* roles: admin (rules, retention, erasure), sales (own records), read-only (analytics);
* per-record ownership checks inside the services, not in the UI;
* HTTPS, secure cookies, session timeouts, rate limiting;
* audit `actor` taken from the authenticated identity.

## Verification performed
* Bandit (`-ll`, medium/high) on `src/`: no issues reported.
* pip-audit on the locked runtime dependencies: no known vulnerabilities at verification time.
* Unit tests for SSRF blocking, redirect re-validation, size cap, content type, robots.txt,
  formula neutralization, markdown escaping, delimiter integrity, and PII absence from prompts.
