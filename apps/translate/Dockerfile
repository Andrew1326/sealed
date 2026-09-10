FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 HF_HOME=/models TRANSFORMERS_OFFLINE=0 HF_HUB_DISABLE_TELEMETRY=1
ARG TORCH=cpu
RUN pip install --index-url https://download.pytorch.org/whl/${TORCH} torch==2.7.0 \
 && pip install transformers==4.51.3 sentencepiece==0.2.0 sacremoses==0.1.1
# bake the weights into the image; at runtime there is no network to fetch anything
RUN python - <<'PY'
from transformers import MarianMTModel, MarianTokenizer
for p in ["en-de","de-en","en-ru","ru-en","en-fr","fr-en"]:
    n=f"Helsinki-NLP/opus-mt-{p}"; MarianTokenizer.from_pretrained(n); MarianMTModel.from_pretrained(n)
PY
ENV TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
COPY manifest.json /sealed/manifest.json
COPY tests/ /sealed/tests/
COPY handler.py /app/handler.py
RUN useradd -u 10001 -M app && chmod -R a+rX /models /app /sealed
USER 10001
ENTRYPOINT ["python", "/app/handler.py"]
