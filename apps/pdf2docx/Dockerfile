FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1
RUN pip install pdf2docx==0.5.8 PyMuPDF==1.24.14
COPY manifest.json /sealed/manifest.json
COPY tests/ /sealed/tests/
COPY handler.py /app/handler.py
RUN useradd -u 10001 -M app && chmod -R a+rX /app /sealed
USER 10001
ENTRYPOINT ["python", "/app/handler.py"]
