"""
Nova Multimodal Embeddings — SKU Validator
Cross-modal validation: compares user's product image against
search result thumbnail images using cosine similarity.

This is NOT an identifier (it has no built-in catalog).
It validates that a search result image matches the user's product photo.
"""

import base64
import json
import os
import sys
from typing import Optional

import boto3
import httpx
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

log = get_logger(__name__)


class NovaValidator:
    """
    Uses Amazon Nova Multimodal Embeddings to validate search results.

    Flow:
      1. Embed user's product image → 1024-dim vector
      2. For each search result thumbnail: embed image → vector
      3. Cosine similarity between user vector and each result vector
      4. Return ranked results with similarity scores

    Threshold: similarity > 0.72 = same product
    """

    MODEL_ID = "amazon.titan-embed-image-v1"
    # Note: Nova Multimodal Embeddings model ID (update when generally available)
    # For hackathon: use Titan Multimodal Embeddings as equivalent
    NOVA_EMBED_MODEL_ID = "amazon.nova-multimodal-embed-v1:0"

    SIMILARITY_THRESHOLD = 0.72

    def __init__(self):
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        )
        self._user_image_vec: Optional[np.ndarray] = None

    def _embed_image(self, image_b64: str) -> np.ndarray:
        """Get 1024-dim embedding for an image."""
        body = {
            "inputImage": image_b64,
            "embeddingConfig": {"outputEmbeddingLength": 1024},
        }

        try:
            response = self.client.invoke_model(
                modelId=self.NOVA_EMBED_MODEL_ID,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            return np.array(result["embedding"])
        except Exception:
            # Fall back to Titan if Nova Multimodal not yet available in region
            response = self.client.invoke_model(
                modelId=self.MODEL_ID,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            return np.array(result["embedding"])

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two vectors (0.0 – 1.0)."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    async def set_reference_image(self, image_b64: str) -> bool:
        """
        Embed the user's product image as the reference vector.
        Call this once per search before validate_results().
        """
        log.info("Embedding reference image for validation")
        try:
            self._user_image_vec = self._embed_image(image_b64)
            log.info("Reference embedding set: shape=%s", self._user_image_vec.shape)
            return True
        except Exception as e:
            log.error("Reference embed failed: %s", e)
            return False

    async def fetch_and_embed_thumbnail(self, image_url: str) -> Optional[np.ndarray]:
        """Download a search result thumbnail and embed it."""
        log.debug("Fetching thumbnail for embedding: %s", image_url[:80])
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(image_url)
                if resp.status_code != 200:
                    log.warning("Thumbnail fetch returned HTTP %d: %s", resp.status_code, image_url[:80])
                    return None
                image_b64 = base64.b64encode(resp.content).decode()
                return self._embed_image(image_b64)
        except Exception as e:
            log.error("Thumbnail fetch/embed failed: %s", e)
            return None

    async def validate_results(self, results: list[dict]) -> list[dict]:
        """
        Validate and re-rank search results by visual similarity to the user's image.

        Each result dict must have: { title, price, url, thumbnail_url, platform, ... }
        Returns results with added: { similarity_score, is_same_product }
        """
        log.info("Validating %d results (threshold=%.2f)", len(results), self.SIMILARITY_THRESHOLD)
        if self._user_image_vec is None:
            log.warning("No reference image set — skipping validation, all results marked valid")
            for r in results:
                r["similarity_score"] = None
                r["is_same_product"]  = True
            return results

        validated = []
        for result in results:
            thumb_url = result.get("thumbnail_url")
            if thumb_url:
                vec = await self.fetch_and_embed_thumbnail(thumb_url)
                if vec is not None:
                    sim = self._cosine_similarity(self._user_image_vec, vec)
                    result["similarity_score"] = round(sim, 3)
                    result["is_same_product"]  = sim >= self.SIMILARITY_THRESHOLD
                    log.debug("platform=%s similarity=%.3f is_match=%s title='%s'",
                              result.get("platform"), sim, result["is_same_product"],
                              result.get("title", "")[:50])
                    validated.append(result)
                    continue

            # No thumbnail or fetch failed — include with null score
            log.debug("No thumbnail for platform=%s title='%s'", result.get("platform"), result.get("title", "")[:50])
            result["similarity_score"] = None
            result["is_same_product"]  = True
            validated.append(result)

        # Sort: same product first, then by similarity score descending
        validated.sort(
            key=lambda r: (
                not r.get("is_same_product", True),
                -(r.get("similarity_score") or 0),
            )
        )
        return validated
