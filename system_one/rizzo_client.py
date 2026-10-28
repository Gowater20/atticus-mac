#!/usr/bin/env python3
"""
Rizzo Flow System 1 Client (Zero-Dependency)
Connects to local Rizzo Flow neural inference server (default: http://127.0.0.1:8017/v1/systemone)
Enforces strict 250ms timeout.
Builds choice questions from catalog and extracts/normalizes output probabilities.
"""

import json
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

DEFAULT_ENDPOINT = "http://127.0.0.1:8017/v1/systemone"
DEFAULT_TIMEOUT = 0.25  # 250ms strict timeout


def build_catalog_options(catalog: Optional[Dict[str, Any]]) -> List[str]:
    """
    Transforms apple_catalog.json into a list of options for Rizzo Flow.
    Extracts action identifiers across all registered apps.
    """
    options: List[str] = []
    if not catalog or not isinstance(catalog, dict):
        return options

    apps = catalog.get("apps", {})
    if not isinstance(apps, dict):
        return options

    for app_name, app_info in apps.items():
        if not isinstance(app_info, dict):
            continue
        actions = app_info.get("actions", {})
        if not isinstance(actions, dict):
            continue
        for action_name in actions.keys():
            options.append(f"{app_name}_{action_name}")

    return options


def _extract_probabilities(body: Any, options: List[str]) -> Dict[str, float]:
    """
    Extracts and normalizes probabilities from all standard structures:
    - answers.intent (dict, mapping, choice+prob, list)
    - questions.intent (probabilities, answers, options)
    - root choice + probability
    - root probabilities mapping or direct option mapping
    """
    extracted: Dict[str, float] = {}
    if not isinstance(body, dict):
        return {opt: 0.0 for opt in options}

    # 1. Structure 1: answers.intent
    answers = body.get("answers", {})
    if isinstance(answers, dict):
        ans_intent = answers.get("intent")
        if isinstance(ans_intent, dict):
            if "probabilities" in ans_intent and isinstance(ans_intent["probabilities"], dict):
                for k, v in ans_intent["probabilities"].items():
                    if isinstance(v, (int, float)):
                        extracted[str(k)] = float(v)
            elif "choice" in ans_intent:
                c = str(ans_intent["choice"])
                p = float(ans_intent.get("probability", ans_intent.get("prob", 1.0)))
                extracted[c] = p
            elif "options" in ans_intent and isinstance(ans_intent["options"], list):
                for item in ans_intent["options"]:
                    if isinstance(item, dict):
                        c = item.get("choice") or item.get("name") or item.get("option")
                        p = item.get("probability") or item.get("prob") or item.get("score", 0.0)
                        if c is not None:
                            extracted[str(c)] = float(p)
            else:
                for k, v in ans_intent.items():
                    if isinstance(v, (int, float)):
                        extracted[str(k)] = float(v)
        elif isinstance(ans_intent, str):
            p = float(answers.get("probability", answers.get("prob", 1.0)))
            extracted[ans_intent] = p

    # 2. Structure 2: questions.intent
    questions = body.get("questions", {})
    if not extracted and isinstance(questions, dict):
        q_intent = questions.get("intent")
        if isinstance(q_intent, dict):
            if "probabilities" in q_intent and isinstance(q_intent["probabilities"], dict):
                for k, v in q_intent["probabilities"].items():
                    if isinstance(v, (int, float)):
                        extracted[str(k)] = float(v)
            elif "choice" in q_intent:
                c = str(q_intent["choice"])
                p = float(q_intent.get("probability", q_intent.get("prob", 1.0)))
                extracted[c] = p
            elif "options" in q_intent and isinstance(q_intent["options"], list):
                for item in q_intent["options"]:
                    if isinstance(item, dict):
                        c = item.get("choice") or item.get("name") or item.get("option")
                        p = item.get("probability") or item.get("prob") or item.get("score", 0.0)
                        if c is not None:
                            extracted[str(c)] = float(p)

    # 3. Structure 3: root probabilities
    if not extracted and "probabilities" in body and isinstance(body["probabilities"], dict):
        for k, v in body["probabilities"].items():
            if isinstance(v, (int, float)):
                extracted[str(k)] = float(v)

    # 4. Structure 4: root choice + probability
    if not extracted and ("choice" in body or "intent" in body):
        c = str(body.get("choice") or body.get("intent"))
        p = float(body.get("probability", body.get("prob", 1.0)))
        extracted[c] = p

    # 5. Structure 5: Direct mapping matching options in root
    if not extracted:
        for opt in options:
            if opt in body and isinstance(body[opt], (int, float)):
                extracted[opt] = float(body[opt])

    # Build normalized output dictionary
    res: Dict[str, float] = {}
    for opt in options:
        res[opt] = float(extracted.get(opt, 0.0))
    for k, v in extracted.items():
        if k not in res:
            res[k] = float(v)

    total = sum(v for v in res.values() if v > 0)
    if total > 1.01:
        res = {k: round(v / total, 4) for k, v in res.items()}
    else:
        res = {k: max(0.0, min(1.0, round(v, 4))) for k, v in res.items()}

    return res


def query_rizzo_intent(
    prompt: str,
    catalog: Optional[Any] = None,
    context: Optional[Any] = None,
    model: str = "system1",
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, float]:
    """
    Executes POST /v1/systemone with JEV wire format:
    {"state": state_str, "model": model, "questions": {"intent": {"type": "choice", "options": options}}}

    Returns normalized probabilities dict.
    Raises urllib.error.URLError, TimeoutError, or Exception on timeout or failure.
    """
    if isinstance(catalog, list):
        options = [str(x) for x in catalog]
    elif isinstance(catalog, dict):
        options = build_catalog_options(catalog)
    else:
        options = []

    if not options:
        options = [
            "word_create_document", "word_insert_title", "word_format_keyword",
            "word_save_document", "word_close_document", "window_snap_left",
            "window_snap_right", "window_maximize", "window_center",
            "window_window_split", "finder_create_folder", "finder_reveal_item"
        ]

    state_str = prompt
    if context:
        if isinstance(context, dict):
            state_str = f"Context: {json.dumps(context, ensure_ascii=False)}\nPrompt: {prompt}"
        else:
            state_str = f"Context: {context}\nPrompt: {prompt}"

    payload = {
        "state": state_str,
        "model": model,
        "questions": {
            "intent": {
                "type": "choice",
                "options": options
            }
        }
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_data = resp.read().decode("utf-8")
        body = json.loads(resp_data)

    return _extract_probabilities(body, options)
