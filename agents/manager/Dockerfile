# The manager's container. Codex has a shell, so it lives here with only the
# manager's office token -- never tokens.json, never the database, never a key.
# Codex auth (the user's ChatGPT login) is a volume at /codex; code is mounted
# read-only at /app; notes, turns and the workspace persist in /state.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm ca-certificates git \
 && npm install -g @openai/codex@0.156.1 \
 && rm -rf /var/lib/apt/lists/* /root/.npm
RUN pip install --no-cache-dir httpx numpy pandas scikit-learn statsmodels "langchain>=1.4,<2" "langchain-openai>=1.7,<2"
RUN printf '#!/bin/sh\nexec python -m agents.manager.office_cli "$@"\n' > /usr/local/bin/office && chmod +x /usr/local/bin/office
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 CODEX_HOME=/codex MANAGER_STATE=/state
WORKDIR /app
CMD ["python", "-m", "agents.manager.runner"]
