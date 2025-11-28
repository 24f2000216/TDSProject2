from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError, validator
import os
from dotenv import load_dotenv
import asyncio
import httpx
import time
import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import re

load_dotenv()

# ==================== LOGGING SETUP ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

# ==================== ENVIRONMENT & CONFIG ====================
SECRET_KEY = os.getenv("SECRET_KEY")
AI_API_URL = os.getenv("AI_API_URL")
AI_TOKEN = os.getenv("AI_TOKEN")

# Validate that required env vars exist
if not SECRET_KEY:
    raise ValueError("SECRET_KEY not found in environment")
if not AI_API_URL or not AI_TOKEN:
    raise ValueError("AI_API_URL or AI_TOKEN not found in environment")

# Configuration constants
MAX_RETRIES = 3
TIME_LIMIT_SECONDS = 180  # 3 minutes
REQUEST_TIMEOUT = 30
PLAYWRIGHT_TIMEOUT = 60000  # 60 seconds in milliseconds

# ==================== PYDANTIC MODELS (Request/Response Validation) ====================
class QuizRequest(BaseModel):
    """Validates incoming quiz request"""
    email: str
    url: str
    secret: str
    
    @validator('email')
    def email_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('email cannot be empty')
        return v
    
    @validator('url')
    def url_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('url cannot be empty')
        return v


class OrganizedQuizData(BaseModel):
    """Validates data returned from AI organization"""
    submit_url: str
    question: str
    provided_data_type: str
    prompt: str
    submition_payload_format: Dict[str, Any]
    provided_data: Optional[str] = None


class AIResponse(BaseModel):
    """Flexible AI response model"""
    choices: Optional[list] = None
    content: Optional[str] = None


class SubmissionResponse(BaseModel):
    """Validates quiz submission response"""
    correct: Optional[bool] = None
    url: Optional[str] = None


# ==================== HELPER FUNCTIONS ====================

def parse_ai_response(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safely extract and parse AI response content.
    AI responses often come in nested format; this extracts the actual text/JSON.
    """
    try:
        # Common pattern: choices[0].message.content
        if 'choices' in response_data:
            content = response_data['choices'][0]['message']['content']
        elif 'content' in response_data:
            content = response_data['content']
        else:
            content = str(response_data)
        
        # If it's JSON-like string, parse it
        content = content.strip()
        if content.startswith('{'):
            return json.loads(content)
        else:
            logger.warning(f"AI response not JSON: {content}")
            return {"raw_content": content}
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.error(f"Failed to parse AI response: {e}")
        raise ValueError(f"Invalid AI response format: {e}")


def validate_submission_response(response_data: Dict[str, Any]) -> SubmissionResponse:
    """Safely validate submission response"""
    try:
        # Handle both boolean and string "true"/"false"
        correct_val = response_data.get('correct')
        if isinstance(correct_val, str):
            correct_val = correct_val.lower() == 'true'
        
        return SubmissionResponse(
            correct=correct_val,
            url=response_data.get('url')
        )
    except Exception as e:
        logger.error(f"Failed to validate submission response: {e}")
        raise


def is_time_limit_exceeded(start_time: float) -> bool:
    """Check if 3 minutes have passed since start"""
    elapsed = time.time() - start_time
    return elapsed > TIME_LIMIT_SECONDS


def validate_url(url: str, whitelist: Optional[list] = None) -> bool:
    """
    Basic SSRF protection: validate URL before making request.
    Optionally check against a whitelist of allowed domains.
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        
        # Reject suspicious protocols
        if parsed.scheme not in ['http', 'https']:
            return False
        
        # If whitelist provided, check domain
        if whitelist:
            return any(domain in parsed.netloc for domain in whitelist)
        
        return True
    except Exception as e:
        logger.error(f"URL validation failed: {e}")
        return False


# ==================== SCRAPING ====================
import asyncio
from urllib.parse import urljoin
import os
import csv
from playwright.async_api import async_playwright

# --- Scrape main quiz page ---
async def scrape_main_quiz_page(quiz_url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(quiz_url, wait_until="networkidle")
        content = await page.content()

        # Find first <a> link on the page (provided data URL)
        a_tag = await page.query_selector("a[href]")
        if a_tag:
            href_raw = await a_tag.get_attribute("href")
            provided_data_url = urljoin(quiz_url, href_raw)
        else:
            provided_data_url = None

        await browser.close()
        return content, provided_data_url


# --- Scrape the provided link with Playwright ---
async def scrape_provided_data(link_url: str):
    if not link_url:
        return None

    parsed_ext = os.path.splitext(link_url)[1].lower()

    # If it's a file (CSV or PDF), use aiohttp
    if parsed_ext in [".csv", ".pdf"]:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(link_url) as resp:
                content_bytes = await resp.read()
                if parsed_ext == ".csv":
                    decoded = content_bytes.decode("utf-8")
                    import csv
                    reader = csv.DictReader(decoded.splitlines())
                    return [row for row in reader]
                else:
                    return content_bytes  # PDF bytes
    else:
        # If it's a webpage that requires JS rendering
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(link_url, wait_until="networkidle")
            content = await page.content()
            await browser.close()
            return content


# --- Main scraper function ---
async def scraper(quiz_url: str):
    quiz_content, provided_data_url = await scrape_main_quiz_page(quiz_url)
    provided_data_content = await scrape_provided_data(provided_data_url)

    return {
        "quiz_url": quiz_url,
        "quiz_page_content": quiz_content,
        "provided_data_url": provided_data_url,
        "provided_data_content": provided_data_content
    }

# ==================== AI FUNCTIONS ====================

async def organize_data(quiz_page_data: str,quiz_page_url: str) -> OrganizedQuizData:
    """
    Use AI to extract and organize quiz data into structured format.
    Validates response before returning.
    """
    logger.info("Starting data organization via AI")
    
    headers = {
        "Authorization": f"Bearer {AI_TOKEN}",
        "Content-Type": "application/json"
    }
    
    system_prompt = """You are an expert data extractor. Extract information from quiz content and return ONLY a valid JSON object with these exact keys:
    {
        "submit_url": "URL where answer should be submitted",
        "question": "The quiz question",
        "provided_data_type": "Type of data (json/csv/pdf/text/api_endpoint)",
        "prompt": "A clear prompt for an LLM to solve this question",
        "submition_payload_format": {JSON template for submission},
        "provided_data": "it contant the content of teh provided data url if any else null"
    }
    Return ONLY the JSON object, no other text."""
    
    user_prompt = f"""Extract information from this quiz page:\n\n{quiz_page_data}\n\nReturn only valid JSON. the quiz_page_data json format provided contain both the quiz_page dataand the provided_url for the question and provided_data conatin teh content of provied url given this make a promot such that it can give price answer in one go"""
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 800,
        "temperature": 0.5
    }
    
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(AI_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            
            ai_response = response.json()
            parsed_content = parse_ai_response(ai_response)
            
            # Validate against Pydantic model
            organized = OrganizedQuizData(**parsed_content)
            logger.info("Data organization successful")
            return organized
            
    except httpx.RequestError as e:
        logger.error(f"AI request failed: {e}")
        raise
    except ValidationError as e:
        logger.error(f"Response validation failed: {e}")
        raise


async def question_solver(
        quiz_page_rl: str,
    question: str,
    provided_data: str,
    submission_format: Dict[str, Any],
    email: str
) -> Dict[str, Any]:
    """
    Use AI to solve the question and format answer for submission.
    Returns validated JSON ready to submit.
    """
    logger.info("Starting question solving")
    
    headers = {
        "Authorization": f"Bearer {AI_TOKEN}",
        "Content-Type": "application/json"
    }
    
    system_prompt = f"""You are a question-answering bot. Solve the question using provided data.
Return ONLY a JSON object matching this format (fill in the answer field):
  {json.dumps(submission_format)}
also make sure that if relatice path is mentioned in the question user quiz_page_url: {quiz_page_rl} to make it absolute url.
Important: Your response must be valid JSON only, no other text."""
    
    user_prompt = f"""Question: {question}
Provided Data: {provided_data}
Email: {email}
Secret: {SECRET_KEY}
Solve this question and return JSON in the specified format."""
    
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 500,
        "temperature": 0.3  # Lower temp for accuracy
    }
    
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(AI_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            
            ai_response = response.json()
            parsed_content = parse_ai_response(ai_response)
            
            logger.info("Question solved successfully")
            return parsed_content
            
    except (httpx.RequestError, ValueError) as e:
        logger.error(f"Question solving failed: {e}")
        raise


# ==================== MAIN PROCESSING LOGIC ====================

async def submit_answer(submit_url: str, payload: Dict[str, Any]) -> SubmissionResponse:
    """Submit answer to quiz endpoint with retry logic"""
    
    if not validate_url(submit_url):
        raise ValueError(f"Invalid or unsafe URL: {submit_url}")
    
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(submit_url, json=payload)
                response.raise_for_status()
                
                submission_response = validate_submission_response(response.json())
                logger.info(f"Answer submitted successfully: {submission_response}")
                return submission_response
                
        except httpx.RequestError as e:
            logger.warning(f"Submission attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise


async def under_the_hood(data: QuizRequest, start_time: float, depth: int = 0) -> Dict[str, Any]:
    """
    Main processing logic: scrape -> organize -> solve -> submit.
    Handles retries and chained quizzes.
    
    Args:
        data: Quiz request data
        start_time: When processing started (for time limit)
        depth: Current recursion depth (prevents infinite loops)
    """
    MAX_DEPTH = 5  # Prevent infinite chaining
    
    if depth > MAX_DEPTH:
        logger.error("Max quiz chain depth exceeded")
        return {"error": "Max quiz chain depth exceeded"}
    
    if is_time_limit_exceeded(start_time):
        logger.info("Time limit exceeded")
        return {"error": "Time limit exceeded"}
    
    try:
        logger.info(f"Processing quiz: {data.url} (depth: {depth})")
        
        # Step 1: Scrape quiz page
        quiz_page_data = await scraper(data.url)
        print(quiz_page_data)
        logger.info(f"Scraped content length: {len(quiz_page_data)}")
        
        # Step 2: Organize data using AI
        organized_data = await organize_data(quiz_page_data,data.url)
        
        logger.info(f"Organized data: {organized_data}")
        
        # Step 3: Solve question using AI
        answer_response = await question_solver(
            quiz_page_rl=data.url,
            question=organized_data.question,
            provided_data=organized_data.provided_data or quiz_page_data,
            submission_format=organized_data.submition_payload_format,
            email=data.email
        )
        logger.info(f"Solved answer response: {answer_response}")
        
        # Step 4: Submit answer
        submission_result = await submit_answer(
            submit_url=organized_data.submit_url,
            payload=answer_response
        )
        logger.info(f"Submission result: {submission_result}")
        # Step 5: Handle response
        if submission_result.correct:
            if submission_result.url:
                # New quiz in chain - recursively process
                logger.info(f"Correct! Processing next quiz: {submission_result.url}")
                new_request = QuizRequest(
                    email=data.email,
                    url=submission_result.url,
                    secret=data.secret
                )
                return await under_the_hood(new_request, start_time, depth + 1)
            else:
                logger.info("Quiz completed successfully!")
                return {"message": "Quiz completed successfully"}
        else:
            # Incorrect answer - retry if time allows
            if not is_time_limit_exceeded(start_time):
                logger.info("Incorrect answer, retrying...")
                await asyncio.sleep(1)  # Brief delay before retry
                return await under_the_hood(data, start_time, depth)
            else:
                return {"error": "Incorrect answer and time limit exceeded"}
    
    except Exception as e:
        logger.error(f"Error in processing: {e}")
        return {"error": str(e)}


# ==================== ENDPOINTS ====================

@app.post("/")
async def receive_request(request: Request, background_tasks: BackgroundTasks):
    """
    Main endpoint: validates request, checks secret, and starts background processing.
    """
    try:
        request_body = await request.json()
    except Exception as e:
        logger.error(f"Invalid JSON: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Invalid JSON in request body"}
        )
    
    # Validate request using Pydantic
    try:
        quiz_request = QuizRequest(**request_body)
    except ValidationError as e:
        logger.warning(f"Validation error: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": f"Bad Request: {e.errors()[0]['msg']}"}
        )
    
    # Validate secret
    if quiz_request.secret != SECRET_KEY:
        logger.warning(f"Invalid secret provided")
        return JSONResponse(
            status_code=403,
            content={"message": "Forbidden: Invalid secret"}
        )
    
    # Add background task to process quiz
    start_time = time.time()
    background_tasks.add_task(under_the_hood, quiz_request, start_time)
    
    logger.info(f"Quiz processing started for email: {quiz_request.email}")
    return JSONResponse(
        status_code=200,
        content={"message": "Request received, processing started"}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
