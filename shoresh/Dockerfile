FROM python:3.13-slim
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

# Corpus engine (relocated from bcv-RAG) reads the precompiled text-fabric corpus
# from $HOME/text-fabric-data — a MOUNTED volume (host /opt/corpus-data), NOT
# baked (baking the cfabric loadAll OOMs the build; see internal-docs/build-on-hetzner.md).
ENV HOME=/root
ENV PORT=8080
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

ENTRYPOINT ["./entrypoint.sh"]
