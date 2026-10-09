# The trader's container: RLM and its LocalREPL in one process (spike 1).
# Code is mounted read-only at /app; the trader's objects persist in /state.
# No model key ever enters this image or this container.
FROM python:3.11-slim
RUN pip install --no-cache-dir rlms==0.1.3 dill==0.4.1 httpx numpy pandas scikit-learn
WORKDIR /app
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "agents.trader.runner"]
