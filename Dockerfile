FROM python:3.13-slim

WORKDIR /app

# Copy source first so editable installs can find the packages
COPY . ./

# Install all dependencies (pip auto-ignores -e if packages already present via COPY)
RUN pip install --no-cache-dir -r requirements.txt

# Default command: run the scheduler daemon
CMD ["python", "-c", "from insightbot.cli import main; main()"]
