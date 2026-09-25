FROM python:3.11-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pyusb==1.2.1
CMD ["python3", "-u", "/app/service.py"]
