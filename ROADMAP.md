# Roadmap

Working order. Engineering first, launch material when media is ready. Updated as items land.

## Done (v0.1.0)
- [x] Sandbox contract, gate, audit, verify pipeline with strace intent detection
- [x] Warm pool, GPU passthrough, Qwen3 quality tier
- [x] Documents: docx/txt/md in and out, pdf to text
- [x] Signed source registry, build-locally install, trust store
- [x] Non-AI apps (docx2pdf)
- [x] Gateway + launcher privilege separation, gVisor via SEALED_RUNTIME
- [x] Control plane API, runner agent, read-only dashboard
- [x] One-line installer, cloud-init, public repo, release

## Engineering, in order
1. [x] **Gateway authentication**: per-client API keys, client label in audit, refuse to bind non-localhost without keys
2. [x] **Control panel UI**: console design system (light/dark), login, runners with detail and per-runner overrides, policy editor with validation, trusted keys, enrol tokens, audit browser with filters, webhook alerts, settings
3. [x] **TLS**: self-signed certs built in, runners pin the control plane fingerprint, both services refuse public binds without TLS, Caddy alternative documented
4. [x] **Pseudonymization pass** for the `standard` tier, plus the remote-provider path it protects (OpenAI-compatible endpoints, refused under any confidential policy)
5. [x] **PDF with layout**: pdf2docx app (PyMuPDF) -> translate -> docx2pdf, PDF in, PDF out
6. [x] **CUDA variants**: registry variants (same signed source, build arg), translate-marian and extract-qwen cuda entries, GPU capability recorded at verify
7. [ ] **More catalog apps** driven by customer conversations: OCR, PII redaction, speech-to-text, spreadsheets
8. [~] **Cloud automation**: built in the enterprise repo (Hetzner list/create/delete with cloud-init enrolment), tested against a fake API; needs a real HCLOUD token for a live run
9. [ ] **Installer test** on a throwaway VM (needs a provider token)

## Editions
- [x] Extension hook in the public control plane; community vs enterprise line drawn (see README)
- [~] Enterprise package (private repo `sealed-enterprise`): license keys and Hetzner cloud automation done; orgs and roles, SSO, audit export, alerting integrations open
- [ ] Hosted control plane

## Launch material (needs AI-generated media, later)
- [ ] Landing page: one-liner, evil-image demo, threat model in plain words, contact
- [ ] Two-minute demo recording
- [ ] Show HN, r/selfhosted, local-AI communities

## Validation, in parallel with everything
- [ ] Route own confidential work through it for a week, log friction
- [ ] Five conversations with translation agencies, law firms, accounting firms

## Deferred by design
- Attested (TEE) cloud tier: only once paying customers ask for it
- Own hosted compute: never without attestation
