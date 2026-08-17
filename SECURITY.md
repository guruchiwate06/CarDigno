# Security Policy for CarDigno

## 1. Supported Versions

Security updates and critical patches are actively applied to the following versions:

| Version | Supported          |
| ------- | ------------------ |
| `0.1.x` | :white_check_mark: |
| `< 0.1` | :x:                |

---

## 2. Reporting a Vulnerability

If you discover a security vulnerability within the CarDigno project, please do **NOT** open a public issue. Instead, report it privately to the maintainers:

- **Security Contact**: Rajguru Chiwate (or open a GitHub Security Advisory in the repository)
- **Response Window**: Within 48 hours with an initial assessment and timeline.

Please include the following in your report:
1. Description of the vulnerability and its potential impact.
2. Step-by-step reproduction instructions or Proof of Concept (PoC).
3. Suggested fix or remediation (if known).

---

## 3. Public Repository & Data Privacy Guidelines

Because CarDigno processes vehicular time-series telemetry and operates network socket endpoints, adhere to the following safety practices:

### A. Environment Configuration & Secrets
- **Never commit `.env` files**: All environment-specific variables, API keys, credentials, and custom database paths must reside in local `.env` files, which are excluded in `.gitignore`.
- Use `.env.example` as a template for local configurations.
- Generate strong secret keys in production environments:
  ```bash
  openssl rand -hex 32
  ```

### B. Network & Socket Exposure
- By default, the ELM327 mock socket stream (`Port 8000`) and the Application API (`Port 8080`) bind strictly to loopback interface `127.0.0.1`.
- **Warning**: Do not expose raw TCP telemetry sockets (`0.0.0.0`) on public networks or untrusted Wi-Fi without firewall isolation, VPN, or TLS encryption.

### C. Vehicular Telemetry & PII Protection
- Telemetry datasets may contain sensitive driving patterns, timestamps, and vehicle parameters.
- Local SQLite databases stored under `database/telemetry.db` are excluded from version control by default.
- When sharing test datasets or reporting issues, sanitize vehicle identifiers (e.g., VIN numbers, exact GPS/spatial traces).
