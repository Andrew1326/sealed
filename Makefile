.PHONY: setup tools apps apps-gpu evil verify verify-gpu test serve
setup:            ## local dev install of the runner
	python3 -m venv .venv && .venv/bin/pip install -q -e ./runner
tools:            ## static strace for intent detection in verify (extracted from alpine)
	.venv/bin/sealed tools
apps:             ## CPU community apps (downloads ~3 GB of weights once)
	docker build -t sealed/translate-marian:0.2.0 apps/translate
	docker build -t sealed/extract-qwen:0.2.0 apps/extract
apps-gpu:         ## quality tier, CUDA build (~25 GB image, needs an NVIDIA GPU with 12+ GB)
	docker build --build-arg TORCH=cu128 -t sealed/qwen3-4b:0.1.0-cuda apps/qwen3
evil:
	docker build -t sealed/evil-translate:0.1.0 apps/evil
verify: apps      ## admission pipeline on the CPU apps
	.venv/bin/sealed verify sealed/translate-marian:0.2.0
	.venv/bin/sealed verify sealed/extract-qwen:0.2.0
verify-gpu: apps-gpu
	.venv/bin/sealed verify sealed/qwen3-4b:0.1.0-cuda --gpu
test: evil        ## prove the sandbox with the evil image, then run text, document and gateway jobs
	bash tests/test_egress.sh
	bash tests/test_e2e.sh
serve:
	.venv/bin/sealed serve
