.PHONY: setup tools apps apps-gpu evil verify verify-gpu sign test serve
setup:            ## local dev install of the runner
	python3 -m venv .venv && .venv/bin/pip install -q -e ./runner -e ./control
tools:            ## static strace for intent detection in verify (extracted from alpine)
	.venv/bin/sealed tools
apps:             ## CPU community apps (downloads ~3 GB of weights once)
	docker build -t sealed/translate-marian:0.3.0 apps/translate
	docker build -t sealed/extract-qwen:0.3.0 apps/extract
	docker build -t sealed/docx2pdf:0.1.0 apps/docx2pdf
apps-gpu:         ## quality tier, CUDA build (~25 GB image, needs an NVIDIA GPU with 12+ GB)
	docker build --build-arg TORCH=cu128 -t sealed/qwen3-4b:0.2.0-cuda apps/qwen3
evil:
	docker build -t sealed/evil-translate:0.1.0 apps/evil
verify: apps      ## admission pipeline on the CPU apps
	.venv/bin/sealed verify sealed/translate-marian:0.3.0
	.venv/bin/sealed verify sealed/extract-qwen:0.3.0
	.venv/bin/sealed verify sealed/docx2pdf:0.1.0
verify-gpu: apps-gpu
	.venv/bin/sealed verify sealed/qwen3-4b:0.2.0-cuda --gpu
sign:             ## package + sign the app sources into registry/ (run after verify)
	.venv/bin/sealed sign apps/translate --image sealed/translate-marian:0.3.0
	.venv/bin/sealed sign apps/extract --image sealed/extract-qwen:0.3.0
	.venv/bin/sealed sign apps/docx2pdf --image sealed/docx2pdf:0.1.0
	.venv/bin/sealed sign apps/qwen3 --image sealed/qwen3-4b:0.2.0-cuda --build-arg TORCH=cu128
test: evil        ## prove the sandbox with the evil image, then run text, document and gateway jobs
	bash tests/test_egress.sh
	bash tests/test_e2e.sh
	bash tests/test_registry.sh
	bash tests/test_compose.sh
	bash tests/test_control.sh
	bash tests/test_auth.sh
	bash tests/test_control_ui.sh
	bash tests/test_tls.sh
serve:
	.venv/bin/sealed serve
