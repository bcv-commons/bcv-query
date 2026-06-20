FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./
ARG SEARCH_EMBEDDER=cloudflare
RUN pip install --no-cache-dir -r requirements.txt
COPY requirements-berel.txt ./
RUN if [ "$SEARCH_EMBEDDER" = "berel" ]; then \
      pip install --no-cache-dir -r requirements-berel.txt; \
    fi

COPY . .

ENV PYTHONPATH=/app
RUN python -m lxx.parse --all
RUN python -m spine.parse

# Bake native models into the image only when using berel mode
RUN if [ "$SEARCH_EMBEDDER" = "berel" ]; then \
      python -c "from transformers import AutoModel, AutoTokenizer; \
        AutoTokenizer.from_pretrained('dicta-il/BEREL_3.0'); \
        AutoModel.from_pretrained('dicta-il/BEREL_3.0'); \
        AutoTokenizer.from_pretrained('bowphs/SPhilBerta'); \
        AutoModel.from_pretrained('bowphs/SPhilBerta')"; \
    fi

ENV PORT=8080
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

ENTRYPOINT ["./entrypoint.sh"]
