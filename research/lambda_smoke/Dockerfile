FROM python:3.12-slim
RUN pip install --no-cache-dir vllm==0.6.6 xgrammar==0.1.13 outlines==0.1.11 "huggingface_hub[hf_transfer]==0.26.2" jsonschema
WORKDIR /smoke
COPY runtime_metadata.py response_schema.py smoke.py ./
ENV HF_HUB_ENABLE_HF_TRANSFER=1
ENV PYTHONUNBUFFERED=1
