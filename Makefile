.PHONY: setup apps evil verify test serve
setup:            ## local dev install of the runner
	python3 -m venv .venv && .venv/bin/pip install -q -e ./runner
apps:             ## build the two community app images (downloads ~3 GB of weights once)
	docker build -t sealed/translate-marian:0.1.0 apps/translate
	docker build -t sealed/extract-qwen:0.1.0 apps/extract
evil:
	docker build -t sealed/evil-translate:0.1.0 apps/evil
verify: apps      ## run the admission pipeline on both apps
	.venv/bin/sealed verify sealed/translate-marian:0.1.0
	.venv/bin/sealed verify sealed/extract-qwen:0.1.0
test: evil        ## prove the sandbox: the evil image must fail to exfiltrate
	bash tests/test_egress.sh
	bash tests/test_e2e.sh
serve:
	.venv/bin/sealed serve
