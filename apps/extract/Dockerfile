FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 HF_HOME=/models HF_HUB_DISABLE_TELEMETRY=1
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.6.0 \
 && pip install transformers==4.51.3 accelerate==1.6.0
RUN python - <<'PY'
from transformers import AutoModelForCausalLM, AutoTokenizer
n="Qwen/Qwen2.5-1.5B-Instruct"; AutoTokenizer.from_pretrained(n); AutoModelForCausalLM.from_pretrained(n)
PY
ENV TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
COPY manifest.json /sealed/manifest.json
COPY tests/ /sealed/tests/
COPY handler.py /app/handler.py
RUN useradd -u 10001 -M app && chmod -R a+rX /models /app /sealed
USER 10001
ENTRYPOINT ["python", "/app/handler.py"]
