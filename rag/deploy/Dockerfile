FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY rag/requirements.txt rag/requirements.txt
RUN pip install --no-cache-dir -r rag/requirements.txt

# Pre-download the BioBERT model so it's baked into the image
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb')"

# Copy scraper + server code
COPY rag/ rag/

# Data dir — will be mounted as a Fly volume in production
RUN mkdir -p rag/data/chroma_db

EXPOSE 8080

# On start: run scrapers to populate DB if empty, then start server
CMD ["sh", "-c", "\
  if [ ! -f rag/data/pubmed_cases.jsonl ]; then \
    echo 'First run: seeding knowledge base...' && \
    python rag/scrapers/pubmed_scraper.py && \
    python rag/scrapers/radiopaedia_scraper.py && \
    python rag/scripts/embed_and_index.py; \
  fi && \
  python rag/scripts/rag_server.py 8080"]
