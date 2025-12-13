# main.py
"""
Main FastAPI application with route logic.
Handles validation, background processing, and orchestration.
"""

import logging
import asyncio
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import uvicorn

from config import settings
from scraper import PageScraper
from llm import LLMClient

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class TaskRequest(BaseModel):
    """Incoming task request."""
    email: str
    secret: str
    url: str

class SubmissionResponse(BaseModel):
    """Response from submission endpoint."""
    correct: bool
    reason: Optional[str] = None
    url: Optional[str] = None
    delay: Optional[int] = None

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_secret(provided: str, expected: str) -> bool:
    """Validate secret."""
    return provided == expected

def validate_email(provided: str, expected: str) -> bool:
    """Validate email (case-insensitive)."""
    return provided.strip().lower() == expected.strip().lower()

def validate_url(url: str) -> tuple[bool, str]:
    """Validate URL format."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Invalid scheme: {parsed.scheme}"
        if not parsed.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, f"URL error: {str(e)}"

# ============================================================================
# FASTAPI APP SETUP
# ============================================================================

app = FastAPI(
    title="Quiz Solver API",
    description="Intelligent quiz solver with LLM integration"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# BACKGROUND PROCESSING
# ============================================================================

async def process_quiz_chain(
    initial_url: str,
    email: str,
    secret: str
):
    """
    Main background task: Process quiz chain.
    
    1. Scrape page
    2. Call LLM for answer
    3. Submit answer
    4. Handle response (correct/incorrect/next URL)
    5. Repeat until completion
    """
    
    logger.info("=" * 80)
    logger.info("🚀 QUIZ PROCESSING STARTED")
    logger.info("=" * 80)
    
    current_url = initial_url
    question_num = 0
    
    # Initialize clients
    scraper = PageScraper(
        browser_timeout_ms=settings.BROWSER_TIMEOUT_MS,
        fetch_timeout=settings.RESOURCE_FETCH_TIMEOUT_SECONDS,
        max_retries=settings.MAX_RETRIES
    )
    
    llm = LLMClient(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS
    )
    
    while current_url and question_num < settings.MAX_ITERATIONS:
        question_num += 1
        logger.info(f"\n📝 QUESTION {question_num}: {current_url}")
        
        try:
            # STEP 1: Scrape page
            logger.info("📥 Scraping page...")
            page_data = await scraper.scrape_everything(current_url)
            
            if not page_data:
                logger.error("❌ Failed to scrape page")
                break
            
            # STEP 2: Get answer from LLM
            logger.info("🤖 Getting answer from LLM...")
            answer = await llm.get_answer(page_data)
            
            if not answer:
                logger.error("❌ Failed to get answer from LLM")
                break
            
            logger.info(f"✅ Generated answer: {answer}")
            
            # STEP 3: Submit answer
            logger.info("📤 Submitting answer...")
            
            # Extract domain from URL
            parsed = urlparse(current_url)
            submit_url = f"https://{parsed.netloc}/submit"
            
            payload = {
                "email": email,
                "secret": secret,
                "url": current_url,
                "answer": answer
            }
            
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(submit_url, json=payload)
                    response.raise_for_status()
                    
                    submission = response.json()
                    logger.info(f"📩 Submission response: {submission}")
                    
                    # STEP 4: Process response
                    if submission.get("correct"):
                        logger.info("✅✅✅ ANSWER CORRECT! ✅✅✅")
                        
                        if submission.get("url"):
                            logger.info(f"➡️  Moving to next question: {submission['url']}")
                            current_url = submission["url"]
                        else:
                            logger.info("🎉 Quiz completed! (No next URL)")
                            break
                    
                    else:
                        # Answer incorrect - retry with feedback
                        reason = submission.get("reason", "Unknown reason")
                        logger.warning(f"❌ Answer incorrect: {reason}")
                        
                        logger.info("🔄 Retrying with feedback...")
                        answer = await llm.get_answer(page_data, previous_feedback=reason)
                        
                        if answer:
                            logger.info(f"✅ Refined answer: {answer}")
                            
                            # Retry submission
                            payload["answer"] = answer
                            response = await client.post(submit_url, json=payload)
                            response.raise_for_status()
                            submission = response.json()
                            
                            if submission.get("correct"):
                                logger.info("✅✅✅ ANSWER CORRECT (RETRY)! ✅✅✅")
                                if submission.get("url"):
                                    current_url = submission["url"]
                                else:
                                    break
                            else:
                                logger.error(f"❌ Still incorrect after retry: {submission.get('reason')}")
                                # Move to next or stop
                                if not submission.get("url"):
                                    break
                        else:
                            logger.error("❌ Failed to get refined answer")
                            break
                    
                    # Rate limiting
                    await asyncio.sleep(1)
            
            except httpx.HTTPError as e:
                logger.error(f"❌ Submission failed: {e}")
                break
        
        except Exception as e:
            logger.error(f"❌ Unexpected error in question {question_num}: {e}")
            break
    
    logger.info("=" * 80)
    logger.info(f"✅ QUIZ PROCESSING COMPLETED (Solved {question_num} questions)")
    logger.info("=" * 80)

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.post("/handle_task")
async def handle_task(request: TaskRequest, background_tasks: BackgroundTasks):
    """
    Main endpoint to receive and process quiz tasks.
    
    Returns immediately with:
    - 403: Wrong secret
    - 400: Wrong email or invalid URL
    - 200: Task accepted, processing started in background
    """
    
    logger.info(f"📨 Received task request: {request.url}")
    
    # VALIDATION 1: Secret (FIRST)
    if not validate_secret(request.secret, settings.SECRET_KEY):
        logger.warning("❌ Invalid secret")
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    # VALIDATION 2: Email
    if not validate_email(request.email, settings.ALLOWED_EMAIL):
        logger.warning(f"❌ Invalid email: {request.email}")
        raise HTTPException(status_code=400, detail="Invalid email")
    
    # VALIDATION 3: URL
    is_valid, msg = validate_url(request.url)
    if not is_valid:
        logger.warning(f"❌ Invalid URL: {msg}")
        raise HTTPException(status_code=400, detail=f"Invalid URL: {msg}")
    
    # All valid - queue background task
    logger.info("✅ All validations passed, queuing background task")
    
    background_tasks.add_task(
        process_quiz_chain,
        request.url,
        request.email,
        request.secret
    )
    
    return {
        "status": "accepted",
        "message": "Task received and queued for processing in background",
        "url": request.url
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Quiz Solver API"
    }

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Quiz Solver API",
        "version": "1.0.0",
        "endpoints": {
            "POST /handle_task": "Submit quiz task (returns 200/400/403)",
            "GET /health": "Health check",
            "GET /": "This endpoint"
        }
    }

# ============================================================================
# STARTUP
# ============================================================================

if __name__ == "__main__":
    logger.info("🚀 Starting Quiz Solver API...")
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=False
    )
