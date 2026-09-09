# sealed

Run AI apps on confidential data **with no way out**.

An app in this network never receives your data. It ships a container. Your runner executes that
container with no network, no writable filesystem, no capabilities, and one exit: an output gate you
control. "Read but not share" is not a promise. It is the kernel refusing the process a socket.

```
your app ──▶ gateway ──▶ sandbox (docker: --network none --read-only --cap-drop ALL …) ──▶ gate ──▶ result
                │                       ▲                                                   │
                │                verified image (digest-pinned)                        audit log
                └──────────────── policy (what may run, what may come out) ─────────────────┘
```

Works on a laptop, an office server, or a VM in your own cloud account. Nothing is hosted by us.

## Quick start

```bash
make setup                 # python venv with the `sealed` CLI
.venv/bin/sealed tools     # static strace for intent detection during verify (from alpine, one time)
make apps                  # build the two community app images (downloads ~3 GB of weights once)
make verify                # admission pipeline: both images must pass to become usable
make test                  # proves the sandbox with a deliberately malicious image, then runs e2e jobs
```

Then:

```bash
echo "This agreement is confidential." | .venv/bin/sealed run translate-marian --op translate -p source=en -p target=de
echo "Acme GmbH signed with Nordwind AB on 12 March 2026 for EUR 250,000." | .venv/bin/sealed run extract-qwen --op extract
.venv/bin/sealed serve     # HTTP gateway on 127.0.0.1:8470  (POST /v1/jobs, GET /v1/apps, GET /v1/audit)
```

Or as a service: `docker compose up -d` (gateway on 127.0.0.1:8470, needs the Docker socket to launch sandboxes).

## What is in the box

| Piece | Where | What it does |
|---|---|---|
| Sandbox contract | `runner/sealed/sandbox.py` | The docker flags every job runs with. Images cannot opt out. `sealed contract <image>` prints them. |
| Gate | `runner/sealed/gate.py` | Enforces output rules (size, allowed keys, verbatim-copy limit) and writes the audit line. |
| Verify | `runner/sealed/verify.py` | Admission pipeline. Produces a report and adds the image ID to the allowlist. |
| Gateway | `runner/sealed/gateway.py` | Local HTTP API for your applications. Confidential policies only route to verified images. |
| Policies | `policies/*.yaml` | `confidential` (verified only, strict) and `standard` (any image, still sandboxed). |
| Spec | `spec/` | Manifest schema and the stdin/stdout job protocol an app must implement. |
| Apps | `apps/` | `translate-marian` (OPUS-MT, 6 pairs), `extract-qwen` (extract + summarize), `evil` (test image). |

## The admission pipeline (`sealed verify`)

1. **Provenance.** Image resolves to a content-addressed ID. The allowlist stores IDs, never tags.
2. **Manifest.** `/sealed/manifest.json` validates against the schema.
3. **Config.** Image must not declare ports or volumes and must not run as root.
4. **Sandbox probe.** From inside the image: egress, rootfs write, setuid all fail.
5. **Conformance.** The image's own fixtures run for every declared operation under the real sandbox.
6. **Intent.** First fixture runs under strace. Any attempt at `socket(AF_INET…)`, `connect`, `mount`,
   `setuid`, `ptrace` and friends rejects the image, even though the sandbox blocked it.
7. **Canary.** A unique token flows through a strict gate policy end to end.
8. **Scan.** Trivy critical CVEs if trivy is installed (advisory).

`apps/evil` is a "translator" that tries HTTP, DNS, raw sockets, rootfs writes, the docker socket,
setuid and mount. `make test` shows all attempts blocked and the image rejected at step 6.

## Threat model, honestly

- **Protects against:** an app image, malicious or buggy, exfiltrating, persisting, or misusing your data.
  The app author is never trusted. The app is testable instead.
- **Trusts:** the Linux kernel, Docker's isolation, and this runner's own code. Same trust the industry
  already places in containers.
- **Residual risk:** a container escape through a kernel bug. Mitigate by patching the host, running the
  runner on a dedicated machine or VM, and optionally switching the runtime to gVisor or Kata (one flag).
- **Does not cover:** hosted APIs (Gemini, GPT) that only exist remotely. They stay outside the guarantee.
  Use the `standard` policy and a pseudonymization pass for those, and know it is a reduction, not a guarantee.
- **Gateway needs the Docker socket.** Same trade-off Coolify makes. The gateway never reads app data
  beyond passing the job in and the result out. A follow-up moves it behind a socket proxy limited to `run`.

## Writing an app

See `spec/PROTOCOL.md`. Minimal shape: a Dockerfile that bakes the model weights in, a `manifest.json`,
fixtures under `/sealed/tests/`, a non-root user, and an entrypoint that reads one JSON job from stdin
and writes one JSON result to stdout. `apps/translate` is 60 lines.

## Roadmap

- Warm pool: keep a verified container alive per app for repeat jobs (still no network), instead of a cold start per job.
- GPU variants of the community images.
- Pseudonymization pass in the gateway for the `standard` tier.
- Signed manifests and a public registry of verified digests.
- gVisor/Kata runtime option and Docker socket proxy.
- Management plane for deploying runners into customer cloud accounts.
