FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer libreoffice-calc libreoffice-impress python3 \
      fonts-dejavu fonts-liberation2 fonts-noto-core fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*
COPY manifest.json /sealed/manifest.json
COPY tests/ /sealed/tests/
COPY handler.py /app/handler.py
RUN useradd -u 10001 -M app && chmod -R a+rX /app /sealed
USER 10001
ENTRYPOINT ["python3", "/app/handler.py"]
