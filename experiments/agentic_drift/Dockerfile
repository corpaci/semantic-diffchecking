# Reproduce the software-company roles using a scoped dependency profile.
FROM python:3.11.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-core.txt /tmp/requirements-core.txt
RUN pip install --no-cache-dir -r /tmp/requirements-core.txt \
    && pip install --no-cache-dir --no-deps metagpt==0.8.2 \
    && pip freeze > /opt/installed-requirements.txt
COPY requirements-runtime.txt /tmp/requirements-runtime.txt
RUN pip install --no-cache-dir -r /tmp/requirements-runtime.txt \
    && pip freeze > /opt/installed-requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AGENTOPS_OPT_OUT=true
WORKDIR /experiment
COPY *.py /experiment/experiments/agentic_drift/
COPY openrouter_config.json /experiment/experiments/agentic_drift/
COPY cases/bankaccount_v1/requirements.json /experiment/experiments/agentic_drift/cases/bankaccount_v1/
ENTRYPOINT ["python", "-m", "experiments.agentic_drift"]
