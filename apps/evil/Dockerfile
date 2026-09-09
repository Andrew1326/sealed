FROM python:3.12-slim
COPY manifest.json /sealed/manifest.json
COPY tests/ /sealed/tests/
COPY handler.py /app/handler.py
RUN useradd -u 10001 -M app
USER 10001
ENTRYPOINT ["python", "/app/handler.py"]
