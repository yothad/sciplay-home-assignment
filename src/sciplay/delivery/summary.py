"""Daily summary text: deterministic template by default; optional LLM wording, validated, with fallback.

No LLM API is called in this project. `summarize(facts, llm=...)` accepts any callable that takes the prompt and
returns JSON text; its output is accepted only if it passes `DigestSummary` validation against the facts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import pandas as pd
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from sciplay.delivery import config as C
from sciplay.lists import config as L

CAUSAL = re.compile(r"\b(because|due to|caused by|as a result of|driven by|led to)\b", re.IGNORECASE)
NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")

PROMPT_TEMPLATE = """You write the opening summary of a daily email for a mobile game studio.
Readers: studio GM, Player support / VIP / CRM leads, game economy designer, product analyst.

Use ONLY the facts in the JSON below. Rules:
- Every number you write must appear in the facts exactly as given (same rounding).
- Mention reasons only by their label from "top_reasons".
- Do not explain why something happened (no "because", "due to", "driven by"); state what the lists show.
- If "data_status" is not "complete", the headline must say the data is incomplete.
- Plain English, no player IDs, no hype.

Return JSON only, matching this schema:
{{"headline": "<one sentence, max 120 characters>",
  "bullets": ["<max 4 bullets, each one sentence>"],
  "data_status": "complete" | "incomplete"}}

FACTS:
{facts_json}
"""

DESIRED_RESULT_EXAMPLE = {
    "headline": "43 on the lists: 30 still open from yesterday, 6 new overnight.",
    "bullets": [
        "Revenue decline: 8 players (3 high priority), the largest share of value at risk.",
        "Technical or payment friction: 11 players, 2 more than yesterday.",
        "Since last evening: 4 handled by owners, 5 left the lists.",
    ],
    "data_status": "complete",
}


REASON_LABELS = {  # short label per reason code, used in summaries and checked by the validator
    "engagement_overdue_return": "away longer than usual",
    "engagement_sessions_drop": "fewer sessions than usual",
    "engagement_days_drop": "fewer active days than usual",
    "engagement_young_vs_peers": "new player less active than peers",
    "friction_crashes": "crashes",
    "friction_incomplete_purchase": "started a purchase but did not finish",
    "friction_load_failures": "loading failures",
    "friction_unhandled_errors": "unhandled errors",
    "friction_failed_purchases": "failed purchases",
    "friction_support_tickets": "support tickets",
    "revenue_spend_drop": "spending dropped",
    "revenue_overdue": "purchase overdue",
    "revenue_valuable_losing_activity": "valuable non-payer losing activity",
    "revenue_behind_forecast": "behind forecast",
    "supporting_cancellations": "recent cancellations",
}


def facts(date: str, game_id: str, today: pd.DataFrame, yday: pd.DataFrame, overdue_n: int,
          data_status: str = "complete", state: pd.DataFrame | None = None, handled_since: int = 0) -> dict:
    lists = {}
    for name in L.PRECEDENCE:
        t, y = today[today["list_type"] == name], yday[yday["list_type"] == name]
        lists[name] = {"players": len(t), "high": int((t["priority"] == "high").sum()),
                       "change_vs_yesterday": int(len(t) - len(y)),
                       "value_at_risk": f"${t['opportunity_gap'].sum():,.2f}"}
    codes = today["reason_codes"].str.split(";").explode().value_counts().head(3)
    return {"date": date, "studio": C.STUDIO_NAMES.get(game_id, game_id), "players_total": len(today),
            "value_at_risk_total": f"${today['opportunity_gap'].sum():,.2f}",
            "new_since_yesterday": int((~today["player_id"].isin(yday["player_id"])).sum()) if len(yday) else len(today),
            "overdue_escalated": int(overdue_n), "lists": lists,
            "still_open_from_yesterday": int((state["state"] == "open").sum()) if state is not None else 0,
            "in_progress": int((state["state"] == "in_progress").sum()) if state is not None else 0,
            "new_overnight": int((state["state"] == "new").sum()) if state is not None else 0,
            "left_lists_overnight": int((~yday["player_id"].isin(today["player_id"])).sum()) if len(yday) else 0,
            "handled_since_last_evening": int(handled_since),
            "top_reasons": [{"label": REASON_LABELS.get(k, k.replace("_", " ")), "players": int(v)} for k, v in codes.items()],
            "data_status": data_status}


def allowed_numbers(f: dict) -> set[str]:
    return {m.replace(",", "").lstrip("$").rstrip("%") for m in NUMBER.findall(json.dumps(f))}


class DigestSummary(BaseModel):
    headline: str = Field(max_length=120)
    bullets: list[str] = Field(max_length=4)
    data_status: str

    @field_validator("headline", "bullets")
    @classmethod
    def grounded(cls, v, info: ValidationInfo):
        f = (info.context or {}).get("facts", {})
        ok, labels = allowed_numbers(f), [r["label"].lower() for r in f.get("top_reasons", [])]
        for text in [v] if isinstance(v, str) else v:
            if CAUSAL.search(text):
                raise ValueError(f"causal claim not supported by the facts: {text!r}")
            for n in NUMBER.findall(text):
                if n.replace(",", "").lstrip("$").rstrip("%") not in ok:
                    raise ValueError(f"number {n} is not in the facts")
            if "reason" in text.lower() and labels and not any(lab in text.lower() for lab in labels):
                raise ValueError(f"reason not taken from top_reasons: {text!r}")
        return v

    @field_validator("data_status")
    @classmethod
    def status_matches(cls, v, info: ValidationInfo):
        f = (info.context or {}).get("facts", {})
        if f and v != f.get("data_status"):
            raise ValueError("data_status does not match the facts")
        return v


def template(f: dict) -> DigestSummary:
    """Deterministic wording. Always valid by construction."""
    if f["data_status"] != "complete":
        head = f"Data incomplete for {f['date']}: lists are provisional."
    else:
        head = (f"{f['players_total']} on the lists: {f['still_open_from_yesterday']} still open from yesterday, "
                f"{f['new_overnight']} new overnight.")
    bullets = []
    for name, d in f["lists"].items():
        hi = f" ({d['high']} high priority)" if d["high"] else ""
        bullets.append(f"{name}: {d['players']} players{hi}, {d['change_vs_yesterday']:+d} vs yesterday, "
                       f"{d['value_at_risk']} at risk.")
    bullets.append(f"Since last evening: {f['handled_since_last_evening']} handled by owners, "
                   f"{f['left_lists_overnight']} left the lists; {f['value_at_risk_total']} of value at risk.")
    return DigestSummary.model_validate({"headline": head, "bullets": bullets[:4], "data_status": f["data_status"]},
                                        context={"facts": f})


def summarize(f: dict, llm: Callable[[str], str] | None = None) -> tuple[DigestSummary, str]:
    """Returns (summary, source) where source is 'llm' or 'template' (fallback on any failure)."""
    if llm is not None:
        try:
            raw = llm(PROMPT_TEMPLATE.format(facts_json=json.dumps(f, indent=2)))
            return DigestSummary.model_validate_json(raw, context={"facts": f}), "llm"
        except Exception:  # noqa: BLE001, S110 -- invalid JSON, ungrounded number, causal claim, API error
            pass
    return template(f), "template"


def to_markdown(s: DigestSummary) -> str:
    return "\n".join([f"**{s.headline}**", ""] + [f"- {b}" for b in s.bullets])
