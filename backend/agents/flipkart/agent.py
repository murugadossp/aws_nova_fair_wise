"""
Flipkart — Nova Act Agent
Searches flipkart.com for a product and returns the top 5 listings.
Config: instructions and schemas in config.yaml.
"""

import os
import sys
from pathlib import Path

import yaml
from nova_act import ActGetResult, NovaAct, Workflow

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from logger import get_logger
from nova_auth import get_or_create_workflow_definition

log = get_logger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _CONFIG = yaml.safe_load(_f)


def _sub(s: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        s = s.replace(f"{{{{{k}}}}}", str(v))
    return s


class FlipkartAgent:

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        log.info("Searching Flipkart: query='%s' max_results=%d", query, max_results)

        os.environ.pop("NOVA_ACT_API_KEY", None)

        workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_FLIPKART") or _CONFIG["workflow_name"]
        base_url = _CONFIG["base_url"]
        url = f"{base_url}/search?q={query.replace(' ', '%20')}"

        get_or_create_workflow_definition(workflow_name)

        headless = os.environ.get("FAREWISE_HEADED", "0") != "1"
        results = []
        try:
            with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
                with NovaAct(workflow=wf, starting_page=url, headless=headless, tty=False) as nova:
                    log.debug("Nova Act browser started for flipkart.com (workflow=%s)", workflow_name)

                    if "pre" in _CONFIG["steps"]:
                        nova.act(_CONFIG["steps"]["pre"]["instruction"])

                    extraction_cfg = _CONFIG["steps"]["extraction"]
                    extraction_instruction = _sub(
                        extraction_cfg["instruction"],
                        max_results=max_results,
                        base_url=base_url,
                    )
                    extracted = nova.act(
                        extraction_instruction,
                        schema=extraction_cfg["schema"],
                    )

                    items = None
                    if isinstance(extracted, ActGetResult) and isinstance(getattr(extracted, "parsed_response", None), list):
                        items = extracted.parsed_response
                    elif isinstance(extracted, list):
                        items = extracted
                    if items is not None:
                        for item in items[:max_results]:
                            results.append({"platform": "flipkart", **item})
                        log.info("Flipkart returned %d results for query='%s'", len(results), query)
                    else:
                        log.warning("Flipkart extraction returned unexpected type: %s", type(extracted))
        except Exception as e:
            log.error("Flipkart search failed for query='%s': %s", query, e)

        return results
