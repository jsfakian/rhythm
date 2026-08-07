# Security Measures — RHYTHM Repository Upload Platform

_Last updated: 2026-07-30_

This document summarizes the security measures in place for the RHYTHM Repository Upload Platform (rhythm.med.uoc.gr), for the benefit of participating institutions and partners evaluating the platform's data protection posture.

## 1. Data Protection & Patient Privacy

- **No PHI is ever stored in the platform's database.** Uploaded DICOM studies must already be pre-anonymized by the submitting institution. The database stores only pseudonymized identifiers (pseudo patient IDs, pseudo study UIDs) — never real names, dates of birth, or medical record numbers.
- **Automated GDPR anonymization validation.** Every uploaded image is checked against a configurable rule set (based on the GDPR-strict de-identification profile) before acceptance. Images that fail validation are rejected and reported; they are never silently accepted.
- **Pseudo-ID collision protection.** A dedicated uniqueness check prevents one institution's pseudonymized patient ID from ever being confused with, or overwriting, another patient's record — a safeguard against accidental re-identification through ID collision.
- **DICOM storage is separated from metadata.** Actual image files are held in a dedicated, access-controlled DICOM server (Orthanc); the web application only ever handles the pseudonymized mapping layer.

## 2. Authentication & Account Security

- **Mandatory two-factor authentication (2FA).** Every account — with no exceptions — must enroll in TOTP-based two-factor authentication (compatible with Google Authenticator, Authy, 1Password, and similar apps) before it can be used. Password alone is never sufficient to sign in.
- **Admin-verified onboarding.** New accounts are inactive until an administrator has reviewed the signup and triggered an email verification link — self-registration alone cannot grant access.
- **Secure password reset**, session expiry after a period of inactivity, and minimum password-strength requirements enforced on every account.
- **Institution-based access control.** Each user belongs to a specific partner institution (identified by a unique site code). Scanners, protocols, and examination data are only ever visible to colleagues at the same institution — never across institutions — while platform administrators retain oversight for support and compliance purposes.

## 3. Network & Infrastructure Security

- **All traffic is served over HTTPS**, with HTTP Strict Transport Security (HSTS) enforced, including subdomains, with preload enabled — browsers will refuse to downgrade a connection to plain HTTP.
- **A dedicated reverse proxy (Caddy)** terminates TLS and is the only publicly reachable entry point. The application server, database, cache, and DICOM server all run on an internal network with no direct exposure to the internet.
- **Standard security response headers are enforced on every response**, including:
  - `Content-Security-Policy` — restricts which scripts/styles/resources a page may load, mitigating cross-site scripting (XSS)
  - `X-Frame-Options: DENY` — prevents the site from being embedded in a hidden frame on another site (clickjacking protection)
  - `X-Content-Type-Options: nosniff` — prevents browsers from misinterpreting file types
  - `Referrer-Policy: strict-origin-when-cross-origin` — limits what referrer information is leaked to third-party sites

## 4. Application Security

- **CSRF protection** on every state-changing request, with secure, HTTPS-only session and CSRF cookies.
- **No inline JavaScript execution.** All client-side code is served from separate, integrity-checked script files rather than embedded directly in pages — closing off an entire class of script-injection attack and enforced by the platform's Content-Security-Policy.
- **Strict upload validation**: file type verification, size limits, and structural (manifest schema) validation are applied before any file is processed.
- **Resumable/chunked upload integrity verification**: large file transfers are split into chunks, each independently verified with SHA-256 and CRC32 checksums, so a corrupted or tampered chunk is detected and rejected before assembly.
- **No use of unsafe shell execution** anywhere in the processing pipeline; all external commands are invoked in a way that cannot be manipulated via crafted input.
- **Full audit logging** of upload submissions, validation outcomes, and processing results, for traceability and compliance review.

## 5. Ongoing Hardening

Security is treated as a continuous process rather than a one-time setup. Recent hardening work includes:

- Migrating from per-user to per-institution data access control, so collaboration within an institution is supported without ever exposing data across institutional boundaries.
- A full audit and remediation of every client-side script on the platform to ensure strict compliance with the Content-Security-Policy, closing a gap that could, in a narrow edge case, have caused a login form to fail insecurely.
- Regular review of authentication flows to ensure credentials are never transmitted or logged in a way that could expose them (e.g., never passed via URL parameters).

We welcome questions from partner institutions' IT and security teams, and are happy to provide additional technical detail on request.
