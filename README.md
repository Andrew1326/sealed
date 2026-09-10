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
make tools                 # static strace for intent detection during verify (from alpine, one time)
make apps                  # build the CPU community apps (downloads ~3 GB of weights once)
make verify                # admission pipeline: images must pass to become usable
make test                  # proves the sandbox with a deliberately malicious image, then runs text, document and gateway jobs
make verify-gpu            # optional quality tier: Qwen3-4B, CUDA build (~25 GB image, NVIDIA GPU with 12+ GB)
```

Then:

```bash
S=.venv/bin/sealed
echo "This agreement is confidential." | $S run translate-marian --op translate -p source=en -p target=de
$S run translate-marian --op translate -p source=en -p target=de --file contract.docx --out contract.de.docx   # docx, txt, md, pdf
$S run extract-qwen --op extract --file contract.docx
$S run qwen3-4b --op translate -p source=en -p target=ru --file contract.docx      # quality tier, any language pair, uses the GPU
$S serve                   # HTTP gateway on 127.0.0.1:8470
```

Gateway API: `POST /v1/jobs` (JSON text jobs), `POST /v1/files` (multipart upload: docx/txt/md/pdf in, same format out
for translate, JSON for extract/summarize/classify), `GET /v1/apps`, `GET /v1/pool`, `GET /v1/audit`.

Or as a service: `docker compose up -d` (gateway on 127.0.0.1:8470). It shares `~/.sealed` with the host, so
`sealed verify` run on the host or via `docker compose exec gateway sealed verify <image>` both feed the same allowlist.

## What is in the box

| Piece | Where | What it does |
|---|---|---|
| Sandbox contract | `runner/sealed/sandbox.py` | The docker flags every job runs with. Images cannot opt out. `sealed contract <image>` prints them. |
| Gate | `runner/sealed/gate.py` | Enforces output rules (size, allowed keys, verbatim-copy limit) and writes the audit line. |
| Verify | `runner/sealed/verify.py` | Admission pipeline. Produces a report and adds the image ID to the allowlist. |
| Gateway | `runner/sealed/gateway.py` | Local HTTP API for your applications. Confidential policies only route to verified images. |
| Policies | `policies/*.yaml` | `confidential` (verified only, strict) and `standard` (any image, still sandboxed). |
| Spec | `spec/` | Manifest schema and the stdin/stdout job protocol an app must implement. |
| Warm pool | `runner/sealed/pool.py` | One loaded container per app kept alive between jobs (same sandbox). First job pays the model load, later jobs take milliseconds. |
| Documents | `runner/sealed/documents.py` | docx/txt/md/pdf in, chunked into jobs, rebuilt with formatting and tables kept (pdf comes back as txt). |
| Apps | `apps/` | `translate-marian` (OPUS-MT, 6 pairs, CPU), `extract-qwen` (Qwen2.5-1.5B, CPU), `qwen3-4b` (quality tier: translate any pair, summarize, extract, classify; GPU), `evil` (test image). |

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

## Measured on this machine (RTX 5080, 32 cores)

| Job | Cold | Warm |
|---|---|---|
| translate-marian, one sentence | 2.6 s | 0.06 s |
| extract-qwen (1.5B, CPU), one paragraph | 18 s | 17 s (CPU-bound) |
| qwen3-4b (GPU), one paragraph, any op | 3.9 s | 3.1 s |
| translate-marian, 6-section contract.docx with table | 10 s | |
| qwen3-4b, same contract to Russian | 21 s | |

## GPU

The runner uses `--gpus all` when the NVIDIA container toolkit is installed. Without it, it passes the device nodes
and the driver's user-space libraries into the sandbox read-only, which works on a stock driver install. To use the
official path instead: `sudo apt install nvidia-container-toolkit && sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`.
Apps declare `requires.gpu: none | optional | required`; the runner enables the GPU automatically for optional/required
apps when the host has one.

## Threat model, honestly

- **Protects against:** an app image, malicious or buggy, exfiltrating, persisting, or misusing your data.
  The app author is never trusted. The app is testable instead.
- **Trusts:** the Linux kernel, Docker's isolation, and this runner's own code. Same trust the industry
  already places in containers.
- **Residual risk:** a container escape through a kernel bug. Mitigate by patching the host, running the
  runner on a dedicated machine or VM, and optionally switching the runtime to gVisor or Kata (one flag).
- **Does not cover:** hosted APIs (Gemini, GPT) that only exist remotely. They stay outside the guarantee.
  Use the `standard` policy and a pseudonymization pass for those, and know it is a reduction, not a guarantee.
- **Warm pool shares one process across jobs of the same tenant.** Use `--cold` or `warm: false` in a policy when jobs must not share memory.
- **Gateway needs the Docker socket.** Same trade-off Coolify makes. The gateway never reads app data
  beyond passing the job in and the result out. A follow-up moves it behind a socket proxy limited to `run`.

## Writing an app

See `spec/PROTOCOL.md`. Minimal shape: a Dockerfile that bakes the model weights in, a `manifest.json`,
fixtures under `/sealed/tests/`, a non-root user, and an entrypoint that reads one JSON job from stdin
and writes one JSON result to stdout. `apps/translate` is 60 lines.

## Roadmap

- Marker-based line alignment for LLM translators (today a chunk whose line count changes is retried unit by unit, which is correct but slower).
- PDF output that keeps layout (currently pdf translates to txt).
- Pseudonymization pass in the gateway for the `standard` tier.
- Signed manifests and a public registry of verified digests.
- gVisor/Kata runtime option and Docker socket proxy.
- Management plane for deploying runners into customer cloud accounts.
