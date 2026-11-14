"""Claude calls with real cost accounting and a hard budget check before each call.

Every call reserves a worst-case cost first. If today's spend plus that reserve
would pass the daily cap (or the job's per-video cap), the call never happens.
"""
import copy
import json
import re
from dataclasses import dataclass

import anthropic
from jsonschema import Draft202012Validator

from .config import MEDIA_DIR
from .db import DB, now
from .events import EventBus

MODEL_STRONG = "claude-opus-5-5"  # scripting, QA
MODEL_RESEARCH = "claude-sonnet-5-5"  # research: your choice on 2026-10-26, about half the cost of Opus
MODEL_FAST = "claude-haiku-5-5"  # JSON repair and other routine formatting

# USD per million tokens: (input, 5-minute cache write, cache read, output).
# Source: platform.claude.com/docs/en/about-claude/pricing, checked 2026-10-26.
PRICES = {
    "claude-opus-5-5": (4.00, 5.00, 0.20, 20.00),
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
    "claude-sonnet-5-5": (2.00, 2.50, 0.10, 10.00),
    "claude-opus-4-8": (5.00, 6.25, 0.50, 25.00),
}
FALLBACK_PRICE = (10.00, 12.50, 1.00, 50.00)  # unknown model: assume the most expensive tier
WEB_SEARCH_USD = 0.01  # $10 per 1,000 searches; web fetch has no extra charge


class BudgetExceeded(Exception):
    pass


class ClaudeFailed(Exception):
    pass


@dataclass
class Result:
    data: dict
    cost_usd: float
    searches: int
    input_tokens: int
    output_tokens: int


def _price(model: str) -> tuple[float, float, float, float]:
    for prefix, p in PRICES.items():
        if model.startswith(prefix):
            return p
    return FALLBACK_PRICE


def usage_cost(model: str, usage) -> tuple[float, int]:
    """Dollar cost of one response's usage block, plus the number of web searches."""
    p_in, p_write, p_read, p_out = _price(model)
    cost = (
        (getattr(usage, "input_tokens", 0) or 0) * p_in
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * p_write
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) * p_read
        + (getattr(usage, "output_tokens", 0) or 0) * p_out
    ) / 1_000_000
    stu = getattr(usage, "server_tool_use", None)
    searches = (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
    return cost + searches * WEB_SEARCH_USD, searches


def api_schema(schema: dict) -> dict:
    """Strip keywords structured outputs may not accept; full validation still runs locally."""
    drop = {"$schema", "title", "minLength", "maxLength", "minimum", "maximum", "maxItems"}

    def walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "properties":
                    # Field names (like a field called "title") are data, not schema keywords: keep them all.
                    out[k] = {name: walk(sub) for name, sub in v.items()}
                    continue
                if k in drop:
                    continue
                if k == "minItems" and v > 1:
                    continue
                if k == "type" and isinstance(v, list):
                    return {**{kk: walk(vv) for kk, vv in node.items() if kk not in drop and kk != "type"},
                            "anyOf": [{"type": t} for t in v]}
                out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(copy.deepcopy(schema))


def _schema_problem(schema: dict, data) -> str | None:
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        return None
    where = "/".join(str(p) for p in errors[0].path) or "(root)"
    return f"{where}: {errors[0].message}"


def _json_from_text(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


class Claude:
    def __init__(self, db: DB, bus: EventBus, client: anthropic.AsyncAnthropic | None = None):
        self.db = db
        self.bus = bus
        self.client = client or anthropic.AsyncAnthropic()

    def _check_budget(self, job: dict, reserve: float, settings: dict) -> None:
        spent_today = self.db.cost_today()
        if spent_today + reserve > settings["daily_budget_usd"]:
            raise BudgetExceeded(
                f"This step could cost up to ${reserve:.2f}; today's spend is ${spent_today:.2f} "
                f"of the ${settings['daily_budget_usd']:.2f} daily cap. Not starting it."
            )
        spent_job = self.db.job_cost(job["id"])
        if spent_job + reserve > settings["per_video_budget_usd"]:
            raise BudgetExceeded(
                f"This step could cost up to ${reserve:.2f}; this video has used ${spent_job:.2f} "
                f"of its ${settings['per_video_budget_usd']:.2f} cap. Not starting it."
            )

    def _record(self, agent: str, job: dict, model: str, usage, note: str) -> tuple[float, int]:
        cost, searches = usage_cost(model, usage)
        self.bus.emit(
            agent, "cost",
            f"{note}: ${cost:.4f} ({usage.input_tokens:,} in, "
            f"{getattr(usage, 'cache_read_input_tokens', 0) or 0:,} cached, {usage.output_tokens:,} out"
            + (f", {searches} web searches" if searches else "") + f", {model}).",
            job["id"], cost_usd=cost,
            details={"model": model, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                     "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                     "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0, "searches": searches},
        )
        return cost, searches

    async def structured(
        self,
        *,
        agent: str,
        job: dict,
        settings: dict,
        system: str,
        prompt: str,
        schema: dict,
        reserve_usd: float,
        effort: str = "high",
        max_tokens: int = 16000,
        web: bool = False,
        max_searches: int = 4,
        max_fetches: int = 4,
        max_turns: int = 4,
        kind: str = "output",
        model: str = MODEL_STRONG,
    ) -> Result:
        """One task for Claude that must end in JSON matching `schema`.

        A single call can't be stopped partway, so its size is bounded up front:
        capped searches and page reads, capped page length, and prompt caching so
        each server-side search step re-reads earlier results at the cache price
        (5% of input) instead of full price.
        """
        tools = []
        if web:
            tools = [
                {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
                {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_fetches, "max_content_tokens": 6000},
            ]
        messages: list = [{"role": "user", "content": prompt}]
        total_cost = 0.0
        total_searches = 0
        tokens_in = tokens_out = 0
        use_format = True
        response = None

        for turn in range(max_turns):
            self._check_budget(job, reserve_usd if turn == 0 else reserve_usd / 2, settings)
            params = dict(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_config={"effort": effort, **({"format": {"type": "json_schema", "schema": api_schema(schema)}} if use_format else {})},
                cache_control={"type": "ephemeral"},
            )
            if model != MODEL_FAST:  # Haiku has no server-side fallback
                params.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            if tools:
                params["tools"] = tools
            try:
                async with self.client.beta.messages.stream(**params) as stream:
                    response = await stream.get_final_message()
            except anthropic.BadRequestError as exc:
                if use_format and turn == 0:
                    # Structured output refused alongside these tools or schema: ask for fenced JSON instead.
                    use_format = False
                    messages = [{"role": "user", "content": prompt + "\n\nEnd your reply with the JSON object in a ```json code block."}]
                    self.bus.emit(agent, "info", "Structured output was refused for this request; asking for plain JSON instead.", job["id"], details={"error": str(exc)[:300]})
                    continue
                raise ClaudeFailed(f"Claude rejected the request: {exc}") from exc

            cost, searches = self._record(agent, job, response.model, response.usage, "Claude call")
            total_cost += cost
            total_searches += searches
            tokens_in += response.usage.input_tokens
            tokens_out += response.usage.output_tokens

            if response.stop_reason == "pause_turn":
                messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": response.content}]
                continue
            if response.stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                raise ClaudeFailed(f"Claude declined this task ({getattr(details, 'category', None) or 'no category'}).")
            if response.stop_reason == "max_tokens":
                partial = "".join(b.text for b in response.content if b.type == "text")
                path = self._save_raw(job, f"{kind}-cutoff", partial)  # keep whatever was paid for
                raise ClaudeFailed(
                    f"Claude's answer was cut off at the {max_tokens:,}-token output limit "
                    f"({len(partial):,} characters of answer before the cutoff; the rest went to reasoning). Partial answer saved to {path}."
                )
            break
        else:
            raise ClaudeFailed(f"Still unfinished after {max_turns} continuation turns.")

        text = "".join(b.text for b in response.content if b.type == "text")
        raw_path = self._save_raw(job, kind, text)  # paid output is kept even if it fails the checks below
        problem = None
        try:
            data = json.loads(text) if use_format else _json_from_text(text)
            problem = _schema_problem(schema, data)
        except (json.JSONDecodeError, ValueError):
            data, problem = None, "not valid JSON"
        if problem:
            self.bus.emit(agent, "info", f"Answer didn't match the {kind} format ({problem}); fixing it with the fast model. Raw answer saved to {raw_path}.", job["id"])
            data, cost = await self._repair(agent, job, settings, text, schema, problem)
            total_cost += cost
            problem = _schema_problem(schema, data)
            if problem:
                raise ClaudeFailed(f"Answer still didn't match the {kind} format after repair ({problem}). Raw answer saved to {raw_path}.")
        return Result(data, round(total_cost, 4), total_searches, tokens_in, tokens_out)

    def latest_raw(self, job_id: int, prefix: str):
        """Newest saved raw answer for a job whose file name starts with `prefix-`, or None."""
        files = sorted((MEDIA_DIR / f"job-{job_id}" / "raw").glob(f"{prefix}-*.txt"))
        return files[-1] if files else None

    def _save_raw(self, job: dict, kind: str, text: str) -> str:
        folder = MEDIA_DIR / f"job-{job['id']}" / "raw"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{kind}-{now().replace(':', '-')}.txt"
        path.write_text(text)
        return str(path)

    async def _repair(self, agent: str, job: dict, settings: dict, text: str, schema: dict, problem: str) -> tuple[dict, float]:
        """Turn a near-miss answer into schema-shaped JSON with the fast model."""
        self._check_budget(job, 0.05, settings)
        params = dict(
            model=MODEL_FAST,
            max_tokens=max(16000, len(text)),  # the repaired answer is about as long as the original
            messages=[{"role": "user", "content": (
                f"This answer failed a format check: {problem}.\n"
                "Convert it into JSON that matches the schema. Keep every fact, URL and wording exactly. "
                "If a required field is missing, fill it only from information already in the answer; invent nothing.\n\n" + text)}],
            output_config={"format": {"type": "json_schema", "schema": api_schema(schema)}},
        )
        try:
            async with self.client.messages.stream(**params) as stream:
                response = await stream.get_final_message()
        except anthropic.BadRequestError as exc:
            raise ClaudeFailed(f"Couldn't repair the answer: {exc}") from exc
        cost, _ = self._record(agent, job, response.model, response.usage, "JSON repair")
        out = "".join(b.text for b in response.content if b.type == "text")
        return json.loads(out), cost
