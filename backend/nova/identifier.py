"""
Nova Lite — Product Identifier
Reads text labels from WhatsApp listing screenshots to extract product name + model.
No reference catalog needed — Nova Lite is a multimodal LLM that reads text.
"""

import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import boto3
from PIL import Image
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

log = get_logger(__name__)


class NovaIdentifier:
    """
    Uses Amazon Nova Lite (multimodal LLM) to read product details
    from a WhatsApp listing screenshot.

    Input:  base64-encoded PNG/JPEG screenshot
    Output: { product_name, model_number, brand, price_in_image, confidence }
    """

    MODEL_ID = "us.amazon.nova-lite-v1:0"

    SYSTEM_PROMPT = """You are a product identification expert specializing in
Indian e-commerce listings. Extract product information from WhatsApp listing
screenshots with high precision. Always respond with valid JSON only."""

    EXTRACTION_PROMPT = """Analyze this WhatsApp product listing screenshot and extract:
1. Full product name (brand + model + variant)
2. Model number (if visible)
3. Brand name
4. Price shown in the listing (in ₹)
5. Key specs visible (storage, color, RAM, etc.)
6. Your confidence score (0.0 to 1.0)

Return ONLY a JSON object with this exact structure:
{
  "product_name": "string",
  "model_number": "string or null",
  "brand": "string",
  "price_in_image": "string or null",
  "specs": ["spec1", "spec2"],
  "search_query": "optimized Amazon/Flipkart search string",
  "confidence": 0.95
}

If no product listing is detected, return: {"error": "no_product_detected"}"""

    def __init__(self):
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )

    def _resize_for_api(self, image_bytes: bytes, max_size: int = 1568) -> bytes:
        """Resize to stay within Nova Lite's image size limits."""
        img = Image.open(io.BytesIO(image_bytes))
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    async def identify_from_image(self, image_b64: str) -> dict:
        """
        Identify product from a base64-encoded screenshot.
        Returns structured product info dict.
        """
        log.info("Identifying product from image (model=%s)", self.MODEL_ID)
        try:
            # Decode and resize image
            image_bytes = base64.b64decode(image_b64)
            image_bytes = self._resize_for_api(image_bytes)
            image_b64_resized = base64.b64encode(image_bytes).decode()
            log.debug("Image resized: %d bytes", len(image_bytes))

            body = {
                "schemaVersion": "messages-v1",
                "system": [{"text": self.SYSTEM_PROMPT}],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": {
                                    "format": "jpeg",
                                    "source": {
                                        "bytes": image_b64_resized,
                                    },
                                }
                            },
                            {"text": self.EXTRACTION_PROMPT},
                        ],
                    }
                ],
                "inferenceConfig": {
                    "maxTokens": 512,
                    "temperature": 0.1,   # Low temp = more deterministic extraction
                    "topP": 0.9,
                },
            }

            response = self.client.invoke_model(
                modelId=self.MODEL_ID,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            result = json.loads(response["body"].read())
            text   = result["output"]["message"]["content"][0]["text"].strip()

            # Strip markdown code fences if present
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

            parsed = json.loads(text)

            if "error" in parsed:
                log.warning("No product detected in image: %s", parsed["error"])
                return {"success": False, "error": parsed["error"]}

            log.info("Identified: '%s' (confidence=%.2f)", parsed.get("product_name"), parsed.get("confidence", 0))
            return {"success": True, **parsed}

        except json.JSONDecodeError:
            log.error("JSON parse failed for image identification response")
            return {"success": False, "error": "parse_failed", "raw": text}
        except Exception as e:
            log.error("Image identification failed: %s", e)
            return {"success": False, "error": str(e)}

    async def identify_from_text(self, query: str) -> dict:
        """
        When user types instead of pasting an image — normalize to structured form.
        """
        log.info("Normalizing text query: '%s'", query)
        try:
            body = {
                "schemaVersion": "messages-v1",
                "system": [{"text": self.SYSTEM_PROMPT}],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": f"""Normalize this product query for Amazon/Flipkart search:
Query: "{query}"

Return ONLY JSON:
{{
  "product_name": "expanded full name",
  "brand": "brand if identifiable or null",
  "model_number": "model if identifiable or null",
  "specs": [],
  "search_query": "optimized search string for Indian e-commerce",
  "confidence": 0.8
}}"""
                            }
                        ],
                    }
                ],
                "inferenceConfig": {"maxTokens": 256, "temperature": 0.1},
            }

            response = self.client.invoke_model(
                modelId=self.MODEL_ID,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            result = json.loads(response["body"].read())
            text   = result["output"]["message"]["content"][0]["text"].strip()
            text   = re.sub(r"^```(?:json)?\n?", "", text)
            text   = re.sub(r"\n?```$", "", text)

            parsed = json.loads(text)
            log.info("Text query normalized: search_query='%s'", parsed.get("search_query", query))
            return {"success": True, **parsed}

        except Exception as e:
            # Fallback: use the raw query
            log.warning("Text normalization failed, using raw query. error=%s", e)
            return {
                "success": True,
                "product_name": query,
                "brand": None,
                "model_number": None,
                "specs": [],
                "search_query": query,
                "confidence": 0.5,
            }
