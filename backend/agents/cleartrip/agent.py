"""
Cleartrip — Nova Act Agent
Searches cleartrip.com for flights and returns top results.
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
from agents.act_handler import ActExceptionHandler

log = get_logger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _CONFIG = yaml.safe_load(_f)


def _sub(s: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        s = s.replace(f"{{{{{k}}}}}", v)
    return s


class CleartripAgent:

    def _get_code(self, city: str) -> str:
        codes = _CONFIG.get("city_codes") or {}
        return codes.get(city.lower().strip(), city.upper()[:3])

    def search(
        self,
        from_city: str,
        to_city: str,
        date: str,
        travel_class: str = "economy",
        user_prompt: str | None = None,
        fetch_offers: bool = True,
    ) -> list[dict] | dict:
        log.info("Searching Cleartrip: %s→%s date=%s class=%s user_prompt=%s", from_city, to_city, date, travel_class, user_prompt)

        os.environ.pop("NOVA_ACT_API_KEY", None)

        workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_CLEARTRIP") or _CONFIG["workflow_name"]
        base_url = _CONFIG["base_url"]
        from_code = self._get_code(from_city)
        to_code = self._get_code(to_city)
        date_ct = self._format_date(date)

        url = (
            f"{base_url}/flights/results?"
            f"from={from_code}&to={to_code}&depart_date={date_ct}"
            f"&adults=1&childs=0&infants=0&class=Economy&intl=n&sd=1"
        )

        get_or_create_workflow_definition(workflow_name)

        headless = os.environ.get("FAREWISE_HEADED", "0") != "1"
        context = {"from": from_city, "to": to_city, "date": date}
        try:
            results: list[dict] = []
            max_steps = int(os.environ.get("NOVA_ACT_MAX_STEPS", _CONFIG.get("max_steps_default", 50)))
            default_criteria = _CONFIG.get("default_criteria", "top 5 cheapest flights")
            criteria = (user_prompt or default_criteria).strip()

            with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
                with NovaAct(workflow=wf, starting_page=url, headless=headless, tty=False) as nova:
                    log.debug("Nova Act browser started for cleartrip.com (workflow=%s)", workflow_name)

                    wait_instruction = _CONFIG["steps"]["wait"]["instruction"]
                    nova.act(wait_instruction)

                    extraction_cfg = _CONFIG["steps"]["extraction"]
                    extraction_instruction = _sub(
                        extraction_cfg["instruction"],
                        criteria=criteria,
                        base_url=base_url,
                    )
                    extraction_schema = extraction_cfg["schema"]
                    extracted = nova.act(
                        extraction_instruction,
                        max_steps=max_steps,
                        schema=extraction_schema,
                    )

                    items = None
                    if isinstance(extracted, ActGetResult) and isinstance(getattr(extracted, "parsed_response", None), list):
                        items = extracted.parsed_response
                    elif isinstance(extracted, list):
                        items = extracted
                    if items is not None:
                        for item in items[:5]:
                            url_val = (item.get("url") or "").strip()
                            if url_val and not url_val.startswith("http"):
                                url_val = base_url + (url_val if url_val.startswith("/") else "/" + url_val)
                            results.append({
                                "platform": "cleartrip",
                                "from_city": from_city,
                                "to_city": to_city,
                                "date": date,
                                "class": travel_class,
                                **{**item, "url": url_val or item.get("url", "")},
                            })
                        log.info("Cleartrip returned %d flights for %s→%s on %s", len(results), from_city, to_city, date)

                        if results and fetch_offers:
                            offers_cfg = _CONFIG["steps"].get("offers")
                            if offers_cfg:
                                try:
                                    offers_instruction = offers_cfg["instruction"]
                                    offers_schema = offers_cfg["schema"]
                                    offers_extracted = nova.act(
                                        offers_instruction,
                                        max_steps=max_steps,
                                        schema=offers_schema,
                                    )
                                    offers_data = None
                                    if isinstance(offers_extracted, ActGetResult) and isinstance(getattr(offers_extracted, "parsed_response", None), dict):
                                        offers_data = offers_extracted.parsed_response
                                    elif isinstance(offers_extracted, dict):
                                        offers_data = offers_extracted
                                    if offers_data:
                                        return {
                                            "flights": results,
                                            "offers_analysis": offers_data.get("offers_applied", []),
                                            "suggestion": offers_data.get("suggestion", ""),
                                        }
                                except Exception as off_e:
                                    log.warning("Cleartrip offers step failed, returning flights only: %s", off_e)
                    else:
                        log.warning("Cleartrip extraction returned unexpected type: %s", type(extracted))
            return results
        except Exception as e:
            return ActExceptionHandler.handle(e, "Cleartrip", context)

    def _format_date(self, date_str: str) -> str:
        try:
            y, m, d = date_str.split("-")
            return f"{d}/{m}/{y}"
        except Exception:
            return date_str
