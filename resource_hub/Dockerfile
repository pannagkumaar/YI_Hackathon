# ---------- Stage 1: Dependencies ----------
FROM python:3.12-slim AS deps

WORKDIR /app

# Copy only the requirements file first — this layer stays cached
COPY requirements.txt ./

# Add pip cache directory
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ---------- Stage 2: Application ----------
FROM python:3.12-slim

WORKDIR /app

# Copy installed site-packages and binaries from deps stage
COPY --from=deps /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy only your code — won't trigger reinstall
COPY . .

EXPOSE 8006
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8006"]
