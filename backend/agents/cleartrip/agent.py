"""
Cleartrip — Nova Act Agent
Searches cleartrip.com for flights and returns ALL results.
Filtering, sorting, and deduplication happen in FlightNormalizer (Python),
not in the Nova Act prompt — the agent is a pure data reader.
Instructions live in .md files under instructions/; config.yaml holds schemas.
"""

import json
import os
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


def _get_instruction(step_cfg: dict) -> str:
    """Instruction text: site_adapter + extractor_prompt (two-layer prompt)."""
    site_file = step_cfg["site_adapter_file"]
    extractor_file = step_cfg["extractor_file"]
    site_path = _AGENT_DIR / site_file
    extractor_path = _AGENT_DIR / extractor_file
    site_content = site_path.read_text(encoding="utf-8").strip()
    extractor_content = extractor_path.read_text(encoding="utf-8").strip()
    return f"{site_content}\n\n{extractor_content}"


def _build_results(items: list[dict], search_url: str, from_city: str, to_city: str, date: str, travel_class: str) -> list[dict]:
    """Convert raw extracted items into normalised result dicts with search page URL."""
    results = []
    for item in items:
        results.append({
            "platform": "cleartrip",
            "from_city": from_city,
            "to_city": to_city,
            "date": date,
            "class": travel_class,
            **item,
            "url": search_url,
        })
    return results


def _hhmm_to_minutes(t: str) -> int:
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def _load_time_buckets() -> list[tuple[str, int, int]]:
    """Read time_buckets from config.yaml → [(label, start_min, end_min), ...]."""
    raw = _CONFIG.get("time_buckets") or []
    buckets = []
    for b in raw:
        buckets.append((
            b["label"],
            _hhmm_to_minutes(b["start"]),
            _hhmm_to_minutes(b["end"]),
        ))
    return buckets


def _build_search_url(
    base_url: str,
    from_code: str,
    to_code: str,
    date_ct: str,
    travel_class: str = "economy",
    filters: dict | None = None,
) -> str:
    """Build Cleartrip results URL, encoding stops and class as query params."""
    class_codes = _CONFIG.get("class_codes") or {}
    cls = class_codes.get(travel_class.lower().strip(), "Economy")

    url = (
        f"{base_url}/flights/results?"
        f"from={from_code}&to={to_code}&depart_date={date_ct}"
        f"&adults=1&childs=0&infants=0&class={cls}&intl=n&sd=1"
    )

    if filters:
        max_stops = filters.get("max_stops")
        if max_stops is not None:
            url += f"&stops={int(max_stops)}"

    return url


def _departure_window_to_checkboxes(window: list[str] | None) -> list[str]:
    """Map a departure_window ["HH:MM", "HH:MM"] to Cleartrip TIMINGS checkbox labels.

    Selects every bucket that overlaps with the inclusive [lo, hi] window.
    Returns [] if no window or window covers all buckets (no pre-filter needed).
    """
    if not window or len(window) != 2:
        return []
    try:
        lo = _hhmm_to_minutes(window[0])
        hi = _hhmm_to_minutes(window[1])
    except (ValueError, AttributeError):
        return []
    buckets = _load_time_buckets()
    if not buckets:
        return []
    labels = [label for label, bstart, bend in buckets if lo < bend and bstart <= hi]
    if len(labels) == len(buckets):
        return []
    return labels


class CleartripAgent:

    def _get_code(self, city: str) -> str:
        codes = _CONFIG.get("city_codes") or {}
        return codes.get(city.lower().strip(), city.upper()[:3])

    @staticmethod
    def _filters_to_criteria(filters: dict | None) -> str:
        """No filtering in Nova Act — FlightNormalizer handles it in Python."""
        return "all available flights"

    def search(
        self,
        from_city: str,
        to_city: str,
        date: str,
        travel_class: str = "economy",
        filters: dict | None = None,
        fetch_offers: bool = False,
    ) -> list[dict] | dict:
        """Extract ALL flights, then optionally check offers in the same session."""
        log.info("Searching Cleartrip: %s→%s date=%s class=%s fetch_offers=%s", from_city, to_city, date, travel_class, fetch_offers)

        os.environ.pop("NOVA_ACT_API_KEY", None)

        workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_CLEARTRIP") or _CONFIG["workflow_name"]
        base_url = _CONFIG["base_url"]
        from_code = self._get_code(from_city)
        to_code = self._get_code(to_city)
        date_ct = self._format_date(date)

        url = _build_search_url(base_url, from_code, to_code, date_ct, travel_class, filters)

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

                    # ── Decide: combined filter+extract (one act) or extraction-only ──
                    checkboxes = _departure_window_to_checkboxes(
                        (filters or {}).get("departure_window"),
                    )
                    extraction_cfg = _CONFIG["steps"]["extraction"]
                    extraction_schema = extraction_cfg["schema"]
                    extracted = None

                    if checkboxes and _CONFIG["steps"].get("extract_with_filter"):
                        combined_cfg = _CONFIG["steps"]["extract_with_filter"]
                        combined_instruction = _sub(
                            _get_instruction(combined_cfg),
                            from_city=from_city,
                            checkboxes=", ".join(f'"{cb}"' for cb in checkboxes),
                        )
                        log.info("Combined filter+extract: TIMINGS %s for %s (single act)", checkboxes, from_city)
                        try:
                            extracted = nova.act(
                                combined_instruction,
                                max_steps=max_steps,
                                schema=extraction_schema,
                            )
                        except Exception as combined_err:
                            log.warning("Combined filter+extract failed (%s), falling back to two-act approach", combined_err)
                            extracted = None

                    if extracted is None:
                        if checkboxes and extracted is None:
                            prefilter_cfg = _CONFIG["steps"].get("pre_filter")
                            if prefilter_cfg:
                                pf_path = _AGENT_DIR / prefilter_cfg["instruction_file"]
                                pf_instruction = _sub(
                                    pf_path.read_text(encoding="utf-8").strip(),
                                    from_city=from_city,
                                    checkboxes=", ".join(f'"{cb}"' for cb in checkboxes),
                                )
                                pf_max_steps = prefilter_cfg.get("max_steps", 10)
                                log.info("Fallback pre-filter: clicking TIMINGS %s for %s", checkboxes, from_city)
                                try:
                                    nova.act(pf_instruction, max_steps=pf_max_steps)
                                except Exception as pf_err:
                                    log.warning("Fallback pre-filter failed (%s), extracting unfiltered", pf_err)

                        extraction_instruction = _sub(
                            _get_instruction(extraction_cfg),
                            criteria=criteria,
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
                        results = _build_results(items, url, from_city, to_city, date, travel_class)
                        log.info("Cleartrip returned %d flights for %s→%s on %s", len(results), from_city, to_city, date)

                        # Offers step: same browser session, agent reads offers from the open page
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
            # If the SDK rejected the response but the model returned valid JSON, try to recover
            if isinstance(e, ActInvalidModelGenerationError):
                raw = getattr(e, "raw_response", None)
                if isinstance(raw, str):
                    raw = raw.strip()
                    if raw:
                        try:
                            data = json.loads(raw)
                            if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "airline" in data[0]:
                                results = _build_results(data, url, from_city, to_city, date, travel_class)
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
