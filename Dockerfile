FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed (e.g. for some crypto libs)
# RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY polymarket/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY polymarket/ ./polymarket/
COPY dashboard/ ./dashboard/

# Set working directory to the python module
WORKDIR /app/polymarket

# Expose the dashboard/api port
EXPOSE 8080

# Run the bot
CMD ["python", "main.py"]
