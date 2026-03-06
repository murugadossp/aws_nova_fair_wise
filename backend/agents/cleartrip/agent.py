"""
Cleartrip — Nova Act Agent
Searches cleartrip.com for flights and returns top results.
Instructions live in .md files under instructions/; config.yaml references them and holds schemas.
"""

import json
import os
import re
import sys
from pathlib import Path

import yaml
from nova_act import ActGetResult, ActInvalidModelGenerationError, NovaAct, Workflow

_AGENT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _AGENT_DIR.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from logger import get_logger
from nova_auth import get_or_create_workflow_definition
from agents.act_handler import ActExceptionHandler

log = get_logger(__name__)

with open(_AGENT_DIR / "config.yaml", encoding="utf-8") as _f:
    _CONFIG = yaml.safe_load(_f)


def _sub(s: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        s = s.replace(f"{{{{{k}}}}}", v)
    return s


def _fix_url_date_if_wrong(url: str, search_date: str) -> str:
    """If the extracted URL contains a 4-digit year that does not match the search date, fix it.
    Prevents hallucinated/wrong-year URLs from opening the wrong Cleartrip page."""
    if not url or not search_date or len(search_date) < 4:
        return url
    search_year = search_date[:4]
    # Match year in path (e.g. ...-07-Mar-2024? or .../2024/...)
    year_in_url = re.search(r"\b(20[12]\d)\b", url)
    if year_in_url and year_in_url.group(1) != search_year:
        return url.replace(year_in_url.group(0), search_year, 1)
    return url


def _schema_substitute_base_url(schema: dict | list | str, base_url: str, escaped: str | None = None) -> dict | list | str:
    """Deep-copy schema and replace {{base_url}} in any string value (e.g. url pattern).
    Uses re.escape(base_url) so that the value is safe inside regex patterns."""
    if escaped is None:
        escaped = re.escape(base_url)
    if isinstance(schema, dict):
        return {k: _schema_substitute_base_url(v, base_url, escaped) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_schema_substitute_base_url(x, base_url, escaped) for x in schema]
    if isinstance(schema, str):
        return schema.replace("{{base_url}}", escaped)
    return schema


def _get_instruction(step_cfg: dict) -> str:
    """Instruction text: site_adapter + extractor_prompt (two-layer prompt)."""
    site_file = step_cfg["site_adapter_file"]
    extractor_file = step_cfg["extractor_file"]
    site_path = _AGENT_DIR / site_file
    extractor_path = _AGENT_DIR / extractor_file
    site_content = site_path.read_text(encoding="utf-8").strip()
    extractor_content = extractor_path.read_text(encoding="utf-8").strip()
    return f"{site_content}\n\n{extractor_content}"


class CleartripAgent:

    def _get_code(self, city: str) -> str:
        codes = _CONFIG.get("city_codes") or {}
        return codes.get(city.lower().strip(), city.upper()[:3])

    @staticmethod
    def _filters_to_criteria(filters: dict | None) -> str:
        """Convert structured filters dict → readable criteria hint for Nova Act."""
        if not filters:
            return "top 5 cheapest flights sorted by price ascending"
        parts = []
        dep_window = filters.get("departure_window")
        if dep_window and len(dep_window) == 2:
            parts.append(f"departure between {dep_window[0]} and {dep_window[1]}")
        if filters.get("max_stops") == 0:
            parts.append("non-stop flights only")
        sort_by = filters.get("sort_by", "price")
        parts.append(f"sort by {sort_by} ascending")
        return "; ".join(parts)

    def search(
        self,
        from_city: str,
        to_city: str,
        date: str,
        travel_class: str = "economy",
        filters: dict | None = None,
        fetch_offers: bool = False,
    ) -> list[dict] | dict:
        """Run extraction first (get flight list), then optionally run offers step later in the same session."""
        log.info("Searching Cleartrip: %s→%s date=%s class=%s filters=%s fetch_offers=%s", from_city, to_city, date, travel_class, filters, fetch_offers)

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
            criteria = self._filters_to_criteria(filters)

            with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
                with NovaAct(workflow=wf, starting_page=url, headless=headless, tty=False) as nova:
                    log.debug("Nova Act browser started for cleartrip.com (workflow=%s)", workflow_name)

                    extraction_cfg = _CONFIG["steps"]["extraction"]
                    extraction_instruction = _sub(
                        _get_instruction(extraction_cfg),
                        criteria=criteria,
                        base_url=base_url,
                    )
                    extraction_schema = _schema_substitute_base_url(
                        extraction_cfg["schema"],
                        base_url,
                    )
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
                            url_val = _fix_url_date_if_wrong(url_val, date)
                            results.append({
                                "platform": "cleartrip",
                                "from_city": from_city,
                                "to_city": to_city,
                                "date": date,
                                "class": travel_class,
                                **{**item, "url": url_val or item.get("url", "")},
                            })
                        log.info("Cleartrip returned %d flights for %s→%s on %s", len(results), from_city, to_city, date)

                        # First get the list; then optionally run offers step later in the same session.
                        if results and fetch_offers:
                            offers_cfg = _CONFIG["steps"].get("offers")
                            if offers_cfg:
                                try:
                                    offers_instruction = _get_instruction(offers_cfg)
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
            # If the SDK rejected the response (e.g. schema validation) but the model returned valid JSON, try to use it
            if isinstance(e, ActInvalidModelGenerationError):
                raw = getattr(e, "raw_response", None)
                if isinstance(raw, str):
                    raw = raw.strip()
                    if raw:
                        try:
                            data = json.loads(raw)
                            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "airline" in data[0]:
                                base_url = _CONFIG["base_url"]
                                results = []
                                for item in data[:5]:
                                    url_val = (item.get("url") or "").strip()
                                    if url_val and not url_val.startswith("http"):
                                        url_val = base_url + (url_val if url_val.startswith("/") else "/" + url_val)
                                    url_val = _fix_url_date_if_wrong(url_val, date)
                                    results.append({
                                        "platform": "cleartrip",
                                        "from_city": from_city,
                                        "to_city": to_city,
                                        "date": date,
                                        "class": travel_class,
                                        **{**item, "url": url_val or item.get("url", "")},
                                    })
                                log.info(
                                    "Cleartrip: recovered %d flights from raw_response after ActInvalidModelGenerationError",
                                    len(results),
                                )
                                return results
                        except (json.JSONDecodeError, KeyError, TypeError):
                            pass
            return ActExceptionHandler.handle(e, "Cleartrip", context)

    def _format_date(self, date_str: str) -> str:
        try:
            y, m, d = date_str.split("-")
            return f"{d}/{m}/{y}"
        except Exception:
            return date_str
