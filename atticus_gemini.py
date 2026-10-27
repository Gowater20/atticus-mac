"""Google Gemini integration for Atticus (Antigravity `agy` CLI + Direct Gemini API fallback).
Isolated in its own module to keep upstream merges conflict-free.
"""
import atexit
import base64
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_AGY_MODEL = 'gemini-3.8-flash-low'
DEFAULT_API_MODEL = 'gemini-2.5-flash'


def _att():
    import sys
    m = sys.modules.get('atticus')
    if m and hasattr(m, 'pref'):
        return m
    return sys.modules.get('__main__')


def _api_key(att):
    att = att or _att()
    return (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or
            str(att.pref('geminiKey', '')).strip() or str(att.pref('apiKey', '')).strip())


def _model(att, default):
    att = att or _att()
    m = str(att.pref('geminiModel', '') or att.pref('apiModel', '')).strip()
    return m if m and m not in ('haiku', 'sonnet', 'opus') else default


def check_gemini_setup(att=None):
    """Verify if `agy` CLI is installed or a Gemini API key is available."""
    att = att or _att()
    agy = shutil.which('agy') or shutil.which('antigravity')
    key = _api_key(att)
    if agy:
        m = _model(att, DEFAULT_AGY_MODEL)
        return {'ok': True, 'need': '', 'client': 'gemini', 'text': f'Using Google Antigravity (agy · {m}).'}
    if key:
        m = _model(att, DEFAULT_API_MODEL)
        return {'ok': True, 'need': '', 'client': 'gemini', 'text': f'Using Google Gemini API ({m}).'}
    return {
        'ok': False,
        'need': 'install',
        'client': 'gemini',
        'text': 'Install Antigravity (`agy`) or set GEMINI_API_KEY in ~/.config/atticus/settings.json ("geminiKey").',
    }


def _gate_approve(att, tool_name, tool_input, cwd):
    """Pass every tool invocation through Atticus's native security & UI gate."""
    att = att or _att()
    payload = json.dumps({'tool_name': tool_name, 'tool_input': tool_input, 'cwd': cwd})
    r = subprocess.run(
        ['/bin/sh', att.ME, '--gate'],
        input=payload, text=True, capture_output=True,
        env={**os.environ, 'ATTICUS_CLIENT': 'pi'}  # 'pi' mode enforces JSON decision + hard deny list
    )
    try:
        ans = json.loads((r.stdout or '').strip().splitlines()[-1])
        return r.returncode == 0 and ans.get('decision') == 'approve', ans.get('reason', 'Blocked by Atticus gate.')
    except Exception:
        return False, 'Atticus could not verify this tool call.'


def run_gemini(task, shots=(), request=None):
    """Execute one Atticus turn using `agy` (preferred) or the Gemini REST API."""
    att = _att()
    att.run.cmds = att.run.ran = []
    att.run.error = ''
    att.run.ok = False
    att.run.why = ''

    status = check_gemini_setup(att)
    if not status['ok']:
        att.run.why = 'setup_needed'
        att.say('!', 'setup')
        return status['text'] + ' Open Atticus Settings to finish setup.', 0, []

    if not att.wait_commit():
        att.run.why = 'cancelled'
        return 'The request was cancelled before the transcript was confirmed.', 0, []

    ask = tempfile.mkdtemp(prefix='atticus-ask-')
    atexit.register(shutil.rmtree, ask, True)
    att.save_request(ask, att.main_ask(task, request)[0])

    agy = shutil.which('agy') or shutil.which('antigravity')
    if agy:
        return _run_agy(att, ask, task, shots, request, agy)
    return _run_api(att, ask, task, shots, request, _api_key(att))


def _extract_agy_tool(obj):
    """Extract tool calls from agy stream-json events (step_update or tool event)."""
    ev = obj.get('event') or obj.get('type') or ''
    if ev == 'step_update':
        s = obj.get('step_update') or {}
        if s.get('step_type') == 'tool':
            tname = s.get('tool_name') or 'Tool'
            tinfo = s.get('tool_info') or {}
            params = tinfo.get('parameters') or {}
            return tname, params
    if ev in ('tool_call', 'tool_use', 'function_call') or 'tool_name' in obj or 'tool' in obj:
        name = obj.get('tool_name') or obj.get('name') or (obj.get('tool') if isinstance(obj.get('tool'), str) else '')
        inp = obj.get('tool_input') or obj.get('input') or obj.get('args') or obj.get('arguments') or {}
        if isinstance(obj.get('tool'), dict):
            name = name or obj['tool'].get('name', '')
            inp = inp or obj['tool'].get('input') or obj['tool'].get('args') or {}
        if isinstance(inp, str):
            try:
                inp = json.loads(inp)
            except ValueError:
                inp = {'command': inp}
        return str(name), inp if isinstance(inp, dict) else {}
    return None, None


def _run_agy(att, ask, task, shots, request, agy_bin):
    model = _model(att, DEFAULT_AGY_MODEL)
    system = att.system_prompt(att.ASK_FIRST if att.pref('safe', True) else att.NEVER)
    try:
        import atticus_i18n
        system += atticus_i18n.system_prompt_addon()
    except Exception:
        pass
    user_text = '\n\n'.join(b['text'] for b in att.user_content(task, request=request))
    shot_lines = [f'- {label}: {path}' for path, label in shots if os.path.exists(path)]
    if shot_lines:
        user_text = 'Screen pictures (inspect if needed):\n' + '\n'.join(shot_lines) + '\n\n' + user_text
    full_prompt = f"{system}\n\n{user_text}"

    args = [agy_bin, '--output-format', 'stream-json']
    args += ['--mode', 'accept-edits'] if att.pref('safe', True) else ['--dangerously-skip-permissions']
    if model:
        args += ['--model', model]
    args += ['-p', full_prompt]

    errors = tempfile.TemporaryFile(mode='w+')
    env = {**os.environ, 'ATTICUS_ASK': ask, 'ATTICUS_CLIENT': 'gemini'}
    try:
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
                             text=True, cwd=ask, start_new_session=True, env=env)
    except BaseException:
        errors.close()
        raise

    p.ask, p.errors = ask, errors
    atexit.register(errors.close)
    atexit.register(att.stop_claude, p)
    signal.signal(signal.SIGTERM, lambda *_: (att.stop_claude(p), att.stop_workers()))

    p.relay_thread = threading.Thread(target=att.relay, args=(p,), daemon=True)
    p.relay_thread.start()

    timed_out = [False]
    def expire():
        timed_out[0] = True
        att.stop_claude(p)
    deadline = threading.Timer(180, expire)
    deadline.daemon = True
    deadline.start()

    reply, cost, steps, cmds = '', 0.0, [], []
    deltas = []
    result_error = False
    streams = os.environ.get('ATTICUS_UI') == '1' and att.pref('showAnswers', 'stream') != 'once'
    shown = ''

    try:
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue

            ev = obj.get('event') or obj.get('type') or ''
            t_name, t_inp = _extract_agy_tool(obj)
            if t_name:
                is_bash = t_name.lower() in ('bash', 'exec', 'shell', 'run_command', 'run_shell_command', 'terminal')
                step = att.label('Bash' if is_bash else t_name, t_inp)
                steps.append(step)
                att.say('▸', step)
                cmd = t_inp.get('command') or t_inp.get('CommandLine') or t_inp.get('cmd') or ''
                if is_bash and isinstance(cmd, str) and cmd:
                    if not att.agent_read_command(cmd):
                        att.run.work = True
                    cmds.append(cmd)
                    att.preview_commands(cmd, ask)
                else:
                    cmds.append(f'<{t_name}>')
                continue

            # Stream deltas from agy or generic agent response
            if ev == 'step_update':
                s = obj.get('step_update') or {}
                if s.get('step_type') == 'agent_response':
                    chunk = s.get('text_delta') or ''
                    if chunk:
                        deltas.append(chunk)
                        if streams:
                            cur = att.streamed_answer(''.join(deltas))
                            if cur != shown:
                                att.say('…', cur)
                                shown = cur

            elif ev in ('text', 'delta', 'content', 'message', 'assistant'):
                chunk = (obj.get('text') or obj.get('delta') or
                         (obj.get('message', {}).get('content') if isinstance(obj.get('message'), dict) else '') or '')
                if isinstance(chunk, str) and chunk:
                    deltas.append(chunk)
                    if streams:
                        cur = att.streamed_answer(''.join(deltas))
                        if cur != shown:
                            att.say('…', cur)
                            shown = cur

            elif ev == 'result' or 'result' in obj:
                res = obj.get('result')
                if isinstance(res, dict):
                    result_error = bool(res.get('is_error') or res.get('error') or res.get('status') == 'ERROR')
                    txt = res.get('text') or res.get('result') or res.get('output') or res.get('response') or ''
                    if isinstance(txt, str) and txt.strip():
                        reply = txt
                    c = res.get('total_cost_usd') or res.get('cost') or 0
                    if isinstance(c, (int, float)):
                        cost = float(c)
                elif isinstance(res, str) and res.strip():
                    reply = res

            elif ev == 'error' or obj.get('is_error'):
                result_error = True
                err_msg = obj.get('error') or obj.get('message') or ''
                if isinstance(err_msg, dict):
                    err_msg = err_msg.get('message') or json.dumps(err_msg)
                if err_msg:
                    att.run.error = att.clean(str(err_msg))

        p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        att.stop_claude(p)
    finally:
        deadline.cancel()
        if p.poll() is None:
            att.stop_claude(p)

    p.relay_thread.join(0.3)

    if not reply and deltas:
        reply = ''.join(deltas)
    reply = att.without_handoff_line(reply).strip()

    errors.seek(0)
    stderr_txt = errors.read(2000).strip()
    if p.stdout:
        p.stdout.close()
    errors.close()

    att.run.ran = cmds
    if timed_out[0]:
        att.run.why = 'timed_out'
        return 'Gemini (agy) timed out before finishing. Please try again.', cost, steps

    if result_error or (not reply and p.returncode):
        detail = att.run.error or stderr_txt or reply[:300]
        att.run.error = att.clean(detail)
        att.run.why = att.failure_why(detail)
        reason = att.clean(detail) or f'exit code {p.returncode}'
        return f'Gemini (agy) stopped: {reason}.', cost, steps

    att.run.ok = bool(reply and not p.returncode and not result_error)
    att.run.cmds = cmds if att.run.ok else []
    if not att.run.why and os.path.exists(os.path.join(ask, 'declined')):
        att.run.ok, att.run.why, att.run.cmds = False, 'cancelled', []
    if not att.run.ok and not att.run.why:
        att.run.why = 'no_reply' if not reply else 'other'

    return reply or 'Gemini returned an empty answer. Please try again.', cost, steps


def _run_api(att, ask, task, shots, request, api_key):
    """Direct Gemini REST API fallback with multi-turn tool calling gated by Atticus."""
    model = _model(att, DEFAULT_API_MODEL)
    system = att.system_prompt(att.ASK_FIRST if att.pref('safe', True) else att.NEVER)
    try:
        import atticus_i18n
        system += atticus_i18n.system_prompt_addon()
    except Exception:
        pass

    parts = []
    for path, label in shots:
        if os.path.exists(path):
            parts.append({'text': label})
            parts.append({'inlineData': {'mimeType': 'image/jpeg', 'data': base64.b64encode(Path(path).read_bytes()).decode()}})
    for b in att.user_content(task, request=request):
        parts.append({'text': b['text']})

    contents = [{'role': 'user', 'parts': parts}]
    tools = [{'functionDeclarations': [
        {
            'name': 'bash',
            'description': 'Run a shell command on the Mac (helpers, osascript, open, mdfind, etc.).',
            'parameters': {
                'type': 'OBJECT',
                'properties': {
                    'command': {'type': 'STRING', 'description': 'The shell command to execute.'},
                    'description': {'type': 'STRING', 'description': '3-8 plain words describing the step.'},
                },
                'required': ['command'],
            },
        },
        {
            'name': 'read_image',
            'description': 'Read a screenshot or image file from disk (e.g. from --look) to inspect it visually.',
            'parameters': {
                'type': 'OBJECT',
                'properties': {'file_path': {'type': 'STRING', 'description': 'Absolute path to the image file.'}},
                'required': ['file_path'],
            },
        },
    ]}]

    os.environ['ATTICUS_ASK'] = ask
    relay_stop = threading.Event()
    def relay_loop():
        while not relay_stop.is_set():
            att.relay(None, ask)
            time.sleep(0.05)
    relay_thread = threading.Thread(target=relay_loop, daemon=True)
    relay_thread.start()

    steps, cmds, bad = [], [], set()
    reply, cost, last_failed = '', 0.0, False
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'

    try:
        for _ in range(15):
            if att.STOPPING:
                att.run.why = 'cancelled'
                break
            payload = {
                'systemInstruction': {'parts': [{'text': system}]},
                'contents': contents,
                'tools': tools,
                'generationConfig': {'temperature': 0.2},
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                err_body = e.read().decode('utf-8', 'replace') if e.fp else str(e)
                att.run.error = att.clean(err_body[:400])
                att.run.why = att.failure_why(f'{e.code} {err_body}', custom=True)
                return f'Gemini API error ({e.code}): {att.run.error}', cost, steps
            except Exception as e:
                att.run.error = att.clean(str(e))
                att.run.why = att.failure_why(str(e))
                return f'Could not reach Gemini API: {att.run.error}', cost, steps

            usage = data.get('usageMetadata', {})
            in_tok = usage.get('promptTokenCount', 0)
            out_tok = usage.get('candidatesTokenCount', 0)
            cost += (in_tok * 0.00000015) + (out_tok * 0.0000006)

            candidates = data.get('candidates') or []
            if not candidates:
                att.run.error = 'No candidates returned by Gemini.'
                att.run.why = 'no_reply'
                return 'Gemini returned no response.', cost, steps

            model_content = candidates[0].get('content') or {'role': 'model', 'parts': []}
            model_parts = model_content.get('parts') or []
            contents.append(model_content)

            fcalls = [p['functionCall'] for p in model_parts if 'functionCall' in p]
            texts = [p['text'] for p in model_parts if 'text' in p and isinstance(p['text'], str)]

            if not fcalls:
                reply = att.without_handoff_line('\n'.join(texts)).strip()
                break

            for t in texts:
                clean_t = att.without_handoff_line(t).strip()
                if clean_t:
                    att.say('·', clean_t)

            resp_parts = []
            for fc in fcalls:
                fname = fc.get('name', '')
                fargs = fc.get('args') or {}
                if fname == 'read_image':
                    fpath = str(fargs.get('file_path', '')).strip()
                    approved, reason = _gate_approve(att, 'read', {'file_path': fpath}, ask)
                    step = att.label('Read', {'file_path': fpath})
                    steps.append(step)
                    att.say('▸', step)
                    cmds.append('<Read>')
                    if not approved or not os.path.isfile(fpath):
                        last_failed = True
                        bad.add(len(cmds) - 1)
                        resp_parts.append({'functionResponse': {'name': fname, 'response': {'error': reason if not approved else 'File not found'}}})
                    else:
                        b64 = base64.b64encode(Path(fpath).read_bytes()).decode()
                        resp_parts.append({'functionResponse': {'name': fname, 'response': {'status': f'Loaded {fpath}'}}})
                        resp_parts.append({'inlineData': {'mimeType': 'image/jpeg', 'data': b64}})
                elif fname == 'bash':
                    cmd = str(fargs.get('command', '')).strip()
                    desc = str(fargs.get('description', '')).strip()
                    approved, reason = _gate_approve(att, 'exec', {'command': cmd, 'description': desc}, ask)
                    step = att.label('Bash', {'command': cmd, 'description': desc})
                    steps.append(step)
                    att.say('▸', step)
                    idx = len(cmds)
                    cmds.append(cmd)
                    if not approved:
                        last_failed = True
                        bad.add(idx)
                        att.run.error = att.clean(reason)
                        resp_parts.append({'functionResponse': {'name': fname, 'response': {'error': reason}}})
                        continue
                    if not att.agent_read_command(cmd):
                        att.run.work = True
                    try:
                        r = subprocess.run(['/bin/zsh', '-c', cmd], capture_output=True, text=True, timeout=120,
                                           cwd=ask, env={**os.environ, 'ATTICUS_ASK': ask})
                        out = (r.stdout or '') + ('\n' + r.stderr if r.stderr else '')
                        out = out.strip()[:16000]
                        last_failed = r.returncode != 0
                        if last_failed:
                            bad.add(idx)
                            att.run.error = att.clean(out or f'exit {r.returncode}')
                        else:
                            att.preview_commands(cmd, ask)
                        att.run.observed.append({'action': cmd, 'error': last_failed, 'result': out})
                        resp_parts.append({'functionResponse': {'name': fname, 'response': {'output': out, 'exit_code': r.returncode}}})
                    except subprocess.TimeoutExpired:
                        last_failed = True
                        bad.add(idx)
                        att.run.error = 'Command timed out'
                        resp_parts.append({'functionResponse': {'name': fname, 'response': {'error': 'Command timed out after 120s'}}})
                else:
                    resp_parts.append({'functionResponse': {'name': fname, 'response': {'error': f'Unknown tool {fname}'}}})

            contents.append({'role': 'user', 'parts': resp_parts})
    finally:
        relay_stop.set()
        relay_thread.join(0.2)

    att.run.ran = cmds
    att.run.ok = bool(reply and not last_failed and not att.run.why)
    att.run.cmds = [c for i, c in enumerate(cmds) if i not in bad] if att.run.ok else []
    if not att.run.why and os.path.exists(os.path.join(ask, 'declined')):
        att.run.ok, att.run.why, att.run.cmds = False, 'cancelled', []
    if not att.run.ok and not att.run.why:
        att.run.why = 'tool_failed' if last_failed else ('no_reply' if not reply else 'other')

    return reply or 'Gemini returned an empty answer. Please try again.', cost, steps
