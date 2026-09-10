# Sealed job protocol (v0)

An app image is compliant when it:

1. Ships `/sealed/manifest.json` matching `manifest.schema.json`.
2. Ships `/sealed/tests/<operation>.json` conformance fixtures for every declared operation.
3. Has an entrypoint that reads jobs as **JSON lines** on stdin, writes one JSON line per job on stdout
   (flushed), and exits on EOF. A single job followed by EOF is the cold path; the runner's warm pool keeps
   the process alive and streams many jobs through it, so load models once and keep them.
4. Runs as a non-root user and needs nothing but its own image contents and `/tmp`.

The runner always executes the image with:

    --network none --read-only --cap-drop ALL --security-opt no-new-privileges
    --tmpfs /tmp --memory <limit> --pids-limit 256 --rm -i

regardless of what the image asks for. There is no way to opt out.

## Job (one line on stdin)

    {"op": "translate", "input": "text...", "params": {"source": "en", "target": "de"}}

`input` is a string for `text/plain` apps, a JSON value for `application/json` apps,
and base64 for `application/octet-stream` apps.

## Result (one line on stdout)

    {"ok": true, "output": "übersetzter Text"}
    {"ok": false, "error": "unsupported language pair"}

`output` is a string for `text/plain` output, a JSON value for `application/json` output.
Anything written to stderr is captured for diagnostics and never leaves the host.

## Conformance fixture format

    [
      {"input": "Hello world", "params": {"source": "en", "target": "de"},
       "expect": {"contains_any": ["Hallo", "Welt"]}},
      {"input": "", "params": {}, "expect": {"ok": false}}
    ]

Supported expectations: `ok`, `contains_any`, `contains_all`, `not_contains`, `json_keys`, `max_chars`.
