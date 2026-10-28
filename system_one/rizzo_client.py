#!/usr/bin/env python3
"""
Rizzo Flow System 1 Client (Zero-Dependency)
Connects to local Rizzo Flow neural inference server (default: http://127.0.0.1:8017/v1/systemone)
Enforces 5.0s timeout for local 4B model inference.
Conforms to Rizzo Flow Pydantic ChoiceQuestion schema with typed criteria dictionary.
Extracts and normalizes output probabilities across wire formats.
"""

import json
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

RIZZO_TIMEOUT = 5.0  # 5.0s timeout: 4B model inference on Mac takes ~3.2s
DEFAULT_ENDPOINT = "http://127.0.0.1:8017/v1/systemone"
DEFAULT_TIMEOUT = RIZZO_TIMEOUT
DEFAULT_MODEL = "rizzo-latest"
DEFAULT_INSTRUCTIONS = "Quale azione desidera compiere l'utente?"


def normalize_action_id(act_key: str, to_dot: bool = False) -> str:
    """
    Normalizes action keys between 'app_action' and 'app.action' formats.
    """
    if not act_key:
        return ""
    if to_dot:
        if "." in act_key:
            return act_key
        parts = act_key.split("_", 1)
        if len(parts) == 2:
            return f"{parts[0]}.{parts[1]}"
        return act_key
    return act_key.replace(".", "_")


def build_catalog_criteria(catalog: Optional[Any]) -> Dict[str, str]:
    """
    Transforms apple_catalog.json or options list into the criteria dictionary
    required by Rizzo Flow Pydantic ChoiceQuestion schema:
    { "app_action": "descrizione dell'azione (triggers)" }
    """
    criteria: Dict[str, str] = {}
    if not catalog:
        return {
            "word_create_document": "Crea nuovo documento con titolo e testo corpo formattati",
            "word_save_document": "Salva il documento attivo in formato docx o esporta in pdf",
            "window_snap_left": "Posiziona la finestra a sinistra"
        }

    if isinstance(catalog, dict) and "apps" in catalog:
        apps = catalog.get("apps", {})
        if isinstance(apps, dict):
            for app_name, app_info in apps.items():
                if not isinstance(app_info, dict):
                    continue
                actions = app_info.get("actions", {})
                if not isinstance(actions, dict):
                    continue
                for action_name, act_data in actions.items():
                    act_key = f"{app_name}_{action_name}"
                    if isinstance(act_data, dict):
                        desc = act_data.get("description", "")
                        triggers = act_data.get("triggers_it", [])
                        if triggers:
                            trig_str = ", ".join(triggers[:2])
                            crit_text = f"{desc} ({trig_str})" if desc else trig_str
                        else:
                            crit_text = desc or act_key
                    else:
                        crit_text = str(act_data)
                    criteria[act_key] = crit_text
    elif isinstance(catalog, dict):
        for k, v in catalog.items():
            if isinstance(v, str):
                criteria[k] = v
            elif isinstance(v, dict):
                desc = v.get("description", "")
                triggers = v.get("triggers_it", [])
                if triggers:
                    trig_str = ", ".join(triggers[:2])
                    criteria[k] = f"{desc} ({trig_str})" if desc else trig_str
                else:
                    criteria[k] = desc or k
            else:
                criteria[k] = str(v)
    elif isinstance(catalog, list):
        for opt in catalog:
            criteria[str(opt)] = str(opt).replace("_", " ")

    # ChoiceQuestion schema requires at least 2 criteria (minProperties=2)
    if len(criteria) < 2:
        if "word_create_document" not in criteria:
            criteria["word_create_document"] = "Crea nuovo documento word"
        if "window_snap_left" not in criteria:
            criteria["window_snap_left"] = "Sposta finestra a sinistra"

    return criteria


def build_catalog_options(catalog: Optional[Dict[str, Any]]) -> List[str]:
    """
    Transforms apple_catalog.json into a list of options for Rizzo Flow.
    Maintained for backward compatibility.
    """
    if isinstance(catalog, list):
        return [str(x) for x in catalog]
    return list(build_catalog_criteria(catalog).keys())


def _extract_probabilities(body: Any, options: List[str]) -> Dict[str, float]:
    """
    Extracts and normalizes probabilities from all standard Rizzo Flow structures:
    - answers.intent (dict, mapping, choice+prob, list)
    - questions.intent (probabilities, answers, options)
    - root choice + probability
    - root probabilities mapping or direct option mapping
    Handles both 'app_action' and 'app.action' naming styles.
    """
    raw_extracted: Dict[str, float] = {}
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
                        raw_extracted[str(k)] = float(v)
            elif "choice" in ans_intent:
                c = str(ans_intent["choice"])
                p = float(ans_intent.get("probability", ans_intent.get("confidence", ans_intent.get("prob", 1.0))))
                raw_extracted[c] = p
            elif "options" in ans_intent and isinstance(ans_intent["options"], list):
                for item in ans_intent["options"]:
                    if isinstance(item, dict):
                        c = item.get("choice") or item.get("name") or item.get("option")
                        p = item.get("probability") or item.get("prob") or item.get("score", 0.0)
                        if c is not None:
                            raw_extracted[str(c)] = float(p)
            else:
                for k, v in ans_intent.items():
                    if isinstance(v, (int, float)):
                        raw_extracted[str(k)] = float(v)
        elif isinstance(ans_intent, str):
            p = float(answers.get("probability", answers.get("confidence", answers.get("prob", 1.0))))
            raw_extracted[ans_intent] = p

    # 2. Structure 2: questions.intent
    questions = body.get("questions", {})
    if not raw_extracted and isinstance(questions, dict):
        q_intent = questions.get("intent")
        if isinstance(q_intent, dict):
            if "probabilities" in q_intent and isinstance(q_intent["probabilities"], dict):
                for k, v in q_intent["probabilities"].items():
                    if isinstance(v, (int, float)):
                        raw_extracted[str(k)] = float(v)
            elif "choice" in q_intent:
                c = str(q_intent["choice"])
                p = float(q_intent.get("probability", q_intent.get("confidence", q_intent.get("prob", 1.0))))
                raw_extracted[c] = p
            elif "options" in q_intent and isinstance(q_intent["options"], list):
                for item in q_intent["options"]:
                    if isinstance(item, dict):
                        c = item.get("choice") or item.get("name") or item.get("option")
                        p = item.get("probability") or item.get("prob") or item.get("score", 0.0)
                        if c is not None:
                            raw_extracted[str(c)] = float(p)

    # 3. Structure 3: root probabilities
    if not raw_extracted and "probabilities" in body and isinstance(body["probabilities"], dict):
        for k, v in body["probabilities"].items():
            if isinstance(v, (int, float)):
                raw_extracted[str(k)] = float(v)

    # 4. Structure 4: root choice + probability
    if not raw_extracted and ("choice" in body or "intent" in body):
        c = str(body.get("choice") or body.get("intent"))
        p = float(body.get("probability", body.get("confidence", body.get("prob", 1.0))))
        raw_extracted[c] = p

    # 5. Structure 5: Direct mapping matching options in root
    if not raw_extracted:
        for opt in options:
            if opt in body and isinstance(body[opt], (int, float)):
                raw_extracted[opt] = float(body[opt])

    # Extract score for each option in options
    res: Dict[str, float] = {}
    for opt in options:
        opt_under = opt.replace(".", "_")
        opt_dot = normalize_action_id(opt, to_dot=True)
        val = 0.0
        if opt in raw_extracted:
            val = raw_extracted[opt]
        elif opt_under in raw_extracted:
            val = raw_extracted[opt_under]
        elif opt_dot in raw_extracted:
            val = raw_extracted[opt_dot]
        res[opt] = float(val)

    # If any keys were in raw_extracted but not in options, keep them
    for k, v in raw_extracted.items():
        k_under = k.replace(".", "_")
        if k not in res and k_under not in res:
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
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
    instructions: str = DEFAULT_INSTRUCTIONS
) -> Dict[str, float]:
    """
    Executes POST /v1/systemone with real Rizzo Flow ChoiceQuestion wire format:
    {
      "state": state_str,
      "model": "rizzo-latest",
      "questions": {
        "intent": {
          "type": "choice",
          "instructions": "Quale azione desidera compiere l'utente?",
          "criteria": { "app_action": "descrizione dell'azione (triggers)" }
        }
      }
    }

    Returns normalized probabilities dict.
    Raises urllib.error.URLError, TimeoutError, or Exception on timeout or failure.
    """
    criteria = build_catalog_criteria(catalog)
    options = list(criteria.keys())

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
                "instructions": instructions,
                "criteria": criteria
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
