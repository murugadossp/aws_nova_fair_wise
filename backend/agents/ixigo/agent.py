"""
Ixigo — Nova Act Agent
Searches ixigo.com for flights and returns top results.
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

_AGENT_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _AGENT_DIR / "config.yaml"
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _CONFIG = yaml.safe_load(_f)


def _sub(s: str, **kwargs: str) -> str:
    for k, v in kwargs.items():
        s = s.replace(f"{{{{{k}}}}}", str(v))
    return s


def _hhmm_to_minutes(t: str) -> int:
    """Parse an HH:MM string and return total minutes since midnight."""
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def _load_time_buckets() -> list[tuple[str, int, int, str]]:
    """Read time_buckets from config.yaml → [(label, start_min, end_min, ixigo_value), ...]."""
    raw = _CONFIG.get("time_buckets") or []
    buckets = []
    for b in raw:
        buckets.append((
            b["label"],
            _hhmm_to_minutes(b["start"]),
            _hhmm_to_minutes(b["end"]),
            b.get("ixigo_value", b["label"].upper().replace(" ", "_")),
        ))
    return buckets


def _window_to_ixigo_values(window: list[str] | None) -> list[str]:
    """Map departure_window or arrival_window [\"HH:MM\", \"HH:MM\"] to Ixigo URL param values.
    Returns overlapping bucket ixigo_values (e.g. [\"EARLY_MORNING\", \"MORNING\"]).
    Returns [] if no window or all buckets would be selected (no filter).
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
    values = [
        ixigo_value
        for _label, bstart, bend, ixigo_value in buckets
        if lo < bend and bstart <= hi
    ]
    if len(values) == len(buckets):
        return []
    return values


def _get_instruction(step_cfg: dict) -> str:
    """Read instruction from file (like Cleartrip). Supports instruction_file with {{criteria}}, {{base_url}} placeholders."""
    instruction_file = step_cfg.get("instruction_file")
    if instruction_file:
        path = _AGENT_DIR / instruction_file
        return path.read_text(encoding="utf-8").strip()
    return (step_cfg.get("instruction") or "").strip()


def _build_search_url(
    base_url: str,
    from_code: str,
    to_code: str,
    date_ixigo: str,
    travel_class: str = "economy",
    filters: dict | None = None,
) -> str:
    """Build Ixigo results URL like a user who only selected source, destination and date.
    No stops, takeOff, or landing — minimal URL so the page loads the same way as a fresh search.
    """
    class_codes = _CONFIG.get("class_codes") or {}
    class_code = class_codes.get(travel_class.lower().strip(), "e")
    return (
        f"{base_url}/search/result/flight"
        f"?from={from_code}&to={to_code}&date={date_ixigo}"
        f"&adults=1&children=0&infants=0&class={class_code}&source=Search+Form"
    )


class IxigoAgent:

    def _get_code(self, city: str) -> str:
        codes = _CONFIG.get("city_codes") or {}
        return codes.get(city.lower().strip(), city.upper()[:3])

    @staticmethod
    def _format_date(date_str: str) -> str:
        """Convert YYYY-MM-DD to DDMMYYYY (Ixigo URL, e.g. 06052026 for 2026-05-06). Never return empty."""
        if not (date_str and date_str.strip()):
            from datetime import date
            today = date.today()
            return f"{today.day:02d}{today.month:02d}{today.year}"
        try:
            parts = date_str.strip().split("-")
            if len(parts) != 3:
                raise ValueError("need YYYY-MM-DD")
            y, m, d = parts[0], parts[1], parts[2]
            d = d.zfill(2)
            m = m.zfill(2)
            out = f"{d}{m}{y}"
            if len(out) != 8:
                raise ValueError("expected 8 chars")
            return out
        except Exception:
            cleaned = date_str.replace("-", "").strip()
            if len(cleaned) == 8 and cleaned.isdigit():
                return cleaned
            from datetime import date
            today = date.today()
            return f"{today.day:02d}{today.month:02d}{today.year}"

    def _get_class_code(self, travel_class: str) -> str:
        codes = _CONFIG.get("class_codes") or {}
        return codes.get(travel_class.lower().strip(), "e")

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
    ) -> list[dict]:
        log.info("Searching Ixigo: %s→%s date=%s class=%s filters=%s", from_city, to_city, date, travel_class, filters)

        os.environ.pop("NOVA_ACT_API_KEY", None)

        workflow_name = os.environ.get("NOVA_ACT_WORKFLOW_IXIGO") or _CONFIG["workflow_name"]
        base_url = _CONFIG["base_url"]
        starting_page = _CONFIG.get("search_form_url") or base_url
        from_code = self._get_code(from_city)
        to_code = self._get_code(to_city)

        get_or_create_workflow_definition(workflow_name)

        headless = os.environ.get("FAREWISE_HEADED", "0") != "1"
        context = {"from": from_city, "to": to_city, "date": date}
        try:
            results: list[dict] = []
            max_steps = int(os.environ.get("NOVA_ACT_MAX_STEPS", _CONFIG.get("max_steps_default", 50)))
            criteria = self._filters_to_criteria(filters)

            with Workflow(workflow_definition_name=workflow_name, model_id="nova-act-latest") as wf:
                with NovaAct(workflow=wf, starting_page=starting_page, headless=headless, tty=False) as nova:
                    log.debug("Nova Act browser started for ixigo.com (workflow=%s), starting at %s", workflow_name, starting_page)

                    # Step 1: Open base URL and fill form — select source, destination, one-way, date, then search
                    fill_cfg = _CONFIG["steps"].get("fill_and_search")
                    if fill_cfg:
                        fill_instruction = _get_instruction(fill_cfg)
                        fill_instruction = _sub(
                            fill_instruction,
                            from_city=from_city,
                            to_city=to_city,
                            from_code=from_code,
                            to_code=to_code,
                            date=date,
                        )
                        fill_max = fill_cfg.get("max_steps", 30)
                        log.info("Ixigo: filling search form (from=%s, to=%s, one-way, date=%s)", from_city, to_city, date)
                        nova.act(fill_instruction, max_steps=fill_max)

                    # Step 2: Wait for results and extract flights
                    extraction_cfg = _CONFIG["steps"]["extraction"]
                    instruction = _get_instruction(extraction_cfg)
                    instruction = _sub(instruction, criteria=criteria, base_url=base_url)
                    extracted = nova.act(
                        instruction,
                        max_steps=max_steps,
                        schema=extraction_cfg["schema"],
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
                                "platform": "ixigo",
                                "from_city": from_city,
                                "to_city": to_city,
                                "date": date,
                                "class": travel_class,
                                **{**item, "url": url_val or item.get("url", "")},
                            })
                        log.info("Ixigo returned %d flights for %s→%s on %s", len(results), from_city, to_city, date)
                    else:
                        log.warning("Ixigo extraction returned unexpected type: %s", type(extracted))
            return results
        except Exception as e:
            return ActExceptionHandler.handle(e, "Ixigo", context)
