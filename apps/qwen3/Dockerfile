FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 HF_HOME=/models HF_HUB_DISABLE_TELEMETRY=1
ARG TORCH=cu128
RUN pip install --index-url https://download.pytorch.org/whl/${TORCH} torch==2.7.0 \
 && pip install transformers==4.51.3 accelerate==1.6.0
COPY manifest.json /sealed/manifest.json
RUN python - <<'PY'
import json
from huggingface_hub import snapshot_download
for m in json.load(open("/sealed/manifest.json"))["models"]:
    snapshot_download(m["id"], revision=m["revision"], allow_patterns=["*.json","*.txt","*.model","*.spm","*.safetensors","pytorch_model.bin","merges.txt","vocab*"])
    print("pinned", m["id"], m["revision"])
PY
ENV TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
COPY tests/ /sealed/tests/
COPY handler.py /app/handler.py
RUN useradd -u 10001 -M app && chmod -R a+rX /models /app /sealed
USER 10001
ENTRYPOINT ["python", "/app/handler.py"]
