FROM python:3.12-slim
WORKDIR /opt/control
COPY control/ control/
RUN pip install --no-cache-dir ./control
ENV SEALED_CONTROL_HOST=0.0.0.0 SEALED_CONTROL_DB=/data/sealed-control.sqlite
VOLUME /data
EXPOSE 8480
CMD ["sealed-control"]
