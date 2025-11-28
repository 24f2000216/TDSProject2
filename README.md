Quiz Solver Bot - FastAPI Application
An AI-powered quiz automation bot that scrapes quiz pages, extracts questions, solves them using AI, and submits answers.

Project Structure
.
├── main.py              # FastAPI application
├── requirements.txt     # Python dependencies
├── Dockerfile          # Docker configuration
└── README.md           # This file
Features
Async Scraping: Uses Playwright to scrape quiz pages with JavaScript rendering
AI-Powered QA: Integrates with OpenAI API to extract and answer questions
Quiz Chaining: Handles multi-step quizzes (quizzes that lead to other quizzes)
Error Handling: Comprehensive logging and retry logic
Security: URL validation and secret-based authentication
Prerequisites
Before deploying, you need:

Hugging Face account
OpenAI API key (for GPT-4o-mini)
Valid environment variables configured
Local Development
Installation
# Clone your repository
git clone <your-repo-url>
cd <project-directory>

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (required for Playwright to work)
playwright install chromium
Environment Setup
Create a .env file in the project root:

SECRET_KEY=your_secret_key_here
AI_API_URL=https://api.openai.com/v1/chat/completions
AI_TOKEN=sk-your-openai-api-key-here
Running Locally
python main.py
The app will run on http://127.0.0.1:8000

Check the health endpoint: http://127.0.0.1:8000/health

Deployment to Hugging Face Spaces
Step 1: Create a New Space
Go to huggingface.co/spaces
Click "Create new Space"
Choose a name (e.g., quiz-solver-bot)
Select "Docker" as the space type
Choose "Public" or "Private" based on your preference
Click "Create Space"
Step 2: Upload Files
Push your code to the Hugging Face repository using Git:

# Initialize git (if not already done)
git init

# Add Hugging Face remote
git remote add origin https://huggingface.co/spaces/YOUR_USERNAME/YOUR_SPACE_NAME

# Add files
git add main.py requirements.txt Dockerfile README.md
git commit -m "Initial deployment"

# Push to Hugging Face
git push -u origin main
Step 3: Configure Secrets
Go to your Space settings (gear icon)
Find "Repository secrets" section
Add these secrets:
SECRET_KEY: Your secret authentication key
AI_API_URL: https://api.openai.com/v1/chat/completions
AI_TOKEN: Your OpenAI API key
Hugging Face will automatically set these as environment variables when the container runs.

Step 4: Modify Dockerfile (for Hugging Face)
Replace the last line in Dockerfile with:

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
(The port 7860 is already in the provided Dockerfile, so it should work as-is)

How It Works
Request Flow
Receive Request (POST /receive_request)

Client sends quiz URL and email
Secret key is validated
Processing starts in background
Scraping

Playwright scrapes the quiz page
Extracts any linked data (CSV, PDF, or webpage)
AI Organization

Sends quiz content to GPT-4o-mini
Extracts: question, submission URL, data type, expected format
Question Solving

AI analyzes question + provided data
Generates answer in required JSON format
Submission

Posts answer to submission endpoint
If correct: processes next quiz in chain (if exists)
If incorrect: retries until time limit
API Endpoints
Health Check

GET /health
Submit Quiz Request

POST /receive_request
Content-Type: application/json

{
  "email": "user@example.com",
  "url": "https://quiz.example.com/quiz1",
  "secret": "your-secret-key"
}
Response:

{
  "message": "Request received, processing started"
}
Configuration Constants
You can modify these in main.py:

MAX_RETRIES: Number of retry attempts for submission (default: 3)
TIME_LIMIT_SECONDS: Maximum processing time (default: 180 = 3 minutes)
REQUEST_TIMEOUT: HTTP request timeout in seconds (default: 30)
PLAYWRIGHT_TIMEOUT: Playwright navigation timeout in milliseconds (default: 60000)
MAX_DEPTH: Maximum quiz chain depth to prevent infinite loops (default: 5)
Troubleshooting
Playwright Installation Issues
If you get browser installation errors:

# Manually install browsers
playwright install chromium

# Or install all browsers
playwright install
Timeout Issues
If quizzes take too long to process, increase TIME_LIMIT_SECONDS in the code.

API Rate Limiting
If you hit OpenAI rate limits, consider:

Increasing delay between retries
Using a higher-tier API account
Implementing request queuing
Development Tips
Adding Logging
Check application logs in Hugging Face Space:

Go to Space → "App" tab → View logs
Look for timestamps and error messages
Testing Locally with Docker
docker build -t quiz-solver .
docker run -p 7860:7860 \
  -e SECRET_KEY=test_key \
  -e AI_API_URL=https://api.openai.com/v1/chat/completions \
  -e AI_TOKEN=sk-your-key \
  quiz-solver
Monitoring
The app logs important events:

When processing starts/ends
When AI calls are made
When submissions succeed/fail
Timing and performance metrics
Important Notes
The application runs async tasks in the background
Requests return immediately; actual processing happens asynchronously
Environment variables are required; deployment will fail without them
Playwright requires significant disk space for browser binaries (~300MB)
Security Considerations
Secret Key Validation: Always validate the secret key
URL Validation: URLs are validated to prevent SSRF attacks
Environment Variables: Never commit .env file to Git
API Keys: Store OpenAI keys securely in Hugging Face Secrets
License
[Add your license here]

Support
For issues or questions, check:

Application logs in Hugging Face Space
Error messages in the response
Console output for detailed stack traces Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference
