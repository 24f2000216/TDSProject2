FROM mcr.microsoft.com/playwright/python:v1.40.0-focal

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (dependencies already included in base image)
RUN playwright install chromium

# Copy application code
COPY main.py .

# Set environment variables (Hugging Face will override these with secrets)
ENV SECRET_KEY=""
ENV AI_API_URL=""
ENV AI_TOKEN=""

# Expose port (Hugging Face uses port 7860)
EXPOSE 7860

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
