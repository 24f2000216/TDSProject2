import httpx
import logging
import json
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class LLMClient:
    """Handles all LLM interactions."""
    
    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: int = 150):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = timeout_seconds
    
    def _headers(self) -> Dict[str, str]:
        """Build request headers."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def get_answer(self, page_content: Dict[str, Any], previous_feedback: str = None) -> Optional[str]:
        """
        Get answer from LLM based on page content.
        
        Args:
            page_content: Extracted page data (html, text, screenshot, etc.)
            previous_feedback: Feedback from previous wrong answer (for retry)
            
        Returns:
            Answer string from LLM or None if failed
        """
        
        # Build system prompt
        system_prompt = """You are a quiz-solving agent. Your task:
1. Analyze the provided quiz content
2. Identify the question
3. Return ONLY the answer, nothing else

Answer Format Rules:
- If number: return just digits (e.g., "42")
- If string: return text without quotes (e.g., "hello")
- If JSON: return valid JSON only
- If code: return code as string
- NO explanation, NO preamble, ONLY the answer
- Do NOT include email, secret, or url in answer"""
        
        # Build user prompt
        user_prompt = f"""Quiz Content:
{json.dumps(page_content, indent=2)}"""
        
        if previous_feedback:
            user_prompt += f"\n\nPrevious attempt was wrong. Hint: {previous_feedback}\nProvide a corrected answer."
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1
        }
        
        try:
            logger.info("🤖 Calling LLM...")
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers()
                )
                response.raise_for_status()
                
                result = response.json()
                answer = result['choices'][0]['message']['content'].strip()
                
                # Clean answer (remove code blocks, quotes, etc.)
                answer = answer.replace("```", "").replace("`", "").strip()
                
                logger.info(f"✅ LLM Answer: {answer[:100]}...")
                return answer
                
        except httpx.HTTPError as e:
            logger.error(f"❌ LLM HTTP error: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ LLM error: {e}")
            return None
    
    async def analyze_screenshot(self, screenshot_base64: str) -> Optional[str]:
        """Analyze screenshot using vision LLM."""
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe what you see in this image."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}
                        }
                    ]
                }
            ],
            "temperature": 0.1
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers()
                )
                response.raise_for_status()
                result = response.json()
                return result['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.error(f"❌ Screenshot analysis error: {e}")
            return None
