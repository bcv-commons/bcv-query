# Thin app image. All heavy/slow layers (pip, model bake, corpus parse) live in
# shoresh-base (see Dockerfile.base); this image only adds app code + the shared
# resources/ and a tiny bit of config, so app-code rebuilds take seconds.
#
# BUILD CONTEXT IS THE REPO ROOT (like bcv-RAG) so the single-source-of-truth
# resources/ dir is reachable:
#   docker build -f shoresh/Dockerfile -t shoresh:latest .
# Build shoresh-base first if missing / after requirements|spine|lxx changes:
#   docker build -f shoresh/Dockerfile.base --build-arg SEARCH_EMBEDDER=berel \
#     -t shoresh-base:latest shoresh
FROM shoresh-base:latest

# App code (the base already built spine.db/lxx.db at /app/{spine,lxx}; those are
# .dockerignore'd so this COPY never clobbers them) + the shared resources baked
# from the repo root. resources/strongs/ and topic_strongs.tsv are excluded via
# the repo-root .dockerignore (big, not read by shoresh).
COPY shoresh /app
COPY resources /app/resources
ENV BCV_RESOURCES_DIR=/app/resources

# Corpus engine (relocated from bcv-RAG) reads the precompiled text-fabric corpus
# from $HOME/text-fabric-data — a MOUNTED volume (host /opt/corpus-data), NOT
# baked (baking the cfabric loadAll OOMs the build; see internal-docs/hosting.md).
ENV PORT=8080
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

ENTRYPOINT ["./entrypoint.sh"]
