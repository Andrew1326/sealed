# Gateway/runner image. Needs the Docker socket to launch sandboxes (same trade-off Coolify makes).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/sealed
COPY runner/ runner/
COPY spec/ spec/
COPY policies/ policies/
RUN pip install --no-cache-dir ./runner
ENV SEALED_SPEC_DIR=/opt/sealed/spec SEALED_POLICY_DIR=/opt/sealed/policies
EXPOSE 8470
CMD ["sealed", "serve", "--host", "0.0.0.0"]
