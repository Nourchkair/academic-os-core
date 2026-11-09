from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from academia_os.study.providers import _codex, _local, output_schema
from tests.test_study import workspace, context_and_payload


def test_codex_transport_uses_chatgpt_login_no_api_fallback_and_constrained_execution(monkeypatch):
    calls = []
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-do-not-forward')
    monkeypatch.setenv('CODEX_API_KEY', 'synthetic-do-not-forward')
    monkeypatch.setattr('academia_os.study.providers.codex_runtime', lambda: {'executable': '/fake/codex', 'models': [], 'recommended_model': None})
    monkeypatch.setattr('academia_os.study.providers.configured_codex_model', lambda: 'configured-model')
    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert 'OPENAI_API_KEY' not in kwargs['env']
        assert 'CODEX_API_KEY' not in kwargs['env']
        if command[1:3] == ['login', 'status']:
            return SimpleNamespace(returncode=0, stdout='', stderr='Logged in using ChatGPT')
        assert '--ignore-user-config' in command and '--ephemeral' in command
        assert command[command.index('--sandbox') + 1] == 'read-only'
        assert command[command.index('--model') + 1] == 'configured-model'
        assert 'features.shell_tool=false' in command and 'features.apps=false' in command
        assert 'features.plugins=false' in command and 'features.multi_agent=false' in command
        assert kwargs['input'] == 'synthetic prompt'
        schema = json.loads(Path(command[command.index('--output-schema') + 1]).read_text())
        assert schema['additionalProperties'] is False
        Path(command[command.index('--output-last-message') + 1]).write_text('{"title":"synthetic"}')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr('academia_os.study.providers.subprocess.run', run)
    assert _codex('synthetic prompt', output_schema('quiz'), None)['title'] == 'synthetic'
    assert len(calls) == 2


def test_codex_api_login_is_rejected_before_any_generation(monkeypatch):
    monkeypatch.setattr('academia_os.study.providers.codex_runtime', lambda: {'executable': '/fake/codex', 'models': [], 'recommended_model': None})
    monkeypatch.setattr('academia_os.study.providers.configured_codex_model', lambda: None)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='Logged in using an API key', stderr='')
    monkeypatch.setattr('academia_os.study.providers.subprocess.run', run)
    with pytest.raises(ValueError, match='will not fall back'):
        _codex('prompt', output_schema('quiz'), None)
    assert len(calls) == 1


def test_codex_reports_access_failure_without_forwarding_private_logs(monkeypatch):
    monkeypatch.setattr('academia_os.study.providers.codex_runtime', lambda: {'executable': '/fake/codex', 'models': [], 'recommended_model': None})
    monkeypatch.setattr('academia_os.study.providers.configured_codex_model', lambda: None)
    def run(command, **kwargs):
        if command[1:3] == ['login', 'status']:
            return SimpleNamespace(returncode=0, stdout='Logged in using ChatGPT', stderr='')
        return SimpleNamespace(returncode=1, stderr="The model is not supported when using Codex with a ChatGPT account. PRIVATE LOG CONTENT")
    monkeypatch.setattr('academia_os.study.providers.subprocess.run', run)
    with pytest.raises(ValueError, match='not available') as error:
        _codex('prompt', output_schema('quiz'), 'unavailable-model')
    assert 'PRIVATE LOG' not in str(error.value)


@pytest.mark.parametrize('protocol', ['ollama', 'openai-compatible'])
def test_local_model_structured_generation_over_loopback(protocol):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append((self.path, value))
            content = json.dumps({'title': 'local response'})
            result = {'message': {'content': content}} if protocol == 'ollama' else {'choices': [{'message': {'content': content}}]}
            data = json.dumps(result).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    server = HTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        endpoint = f'http://127.0.0.1:{server.server_port}' + ('/v1' if protocol == 'openai-compatible' else '')
        result = _local('synthetic prompt', output_schema('quiz'), 'installed-local-model', endpoint, protocol)
        assert result['title'] == 'local response'
        path, payload = received[0]
        assert path == ('/api/chat' if protocol == 'ollama' else '/v1/chat/completions')
        assert payload['stream'] is False
        assert payload['model'] == 'installed-local-model'
        assert payload['messages'][0]['content'] == 'synthetic prompt'
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)


def test_browser_bridge_and_agent_commands_share_study_records(workspace):
    from academia_os.config import save_config
    from academia_os.web import run_cli_command
    from tests.test_web import running_server, request, command_body
    config, _, _, source, service = workspace
    profile = Path(config['runtime']['install_directory']) / 'profile.json'; save_config(profile, config)
    context, payload = context_and_payload(service, source)
    source_id = context['sources'][0]['id']
    runner = lambda command, args: run_cli_command(command, args, profile=profile)
    with running_server(profile.parent, runner=runner) as server:
        code, _, response = request(server, 'POST', '/api/v1/command', body=command_body('study', ['create', '--course', 'POL 2103', '--source', source_id, '--payload-json', json.dumps(payload)]), headers={'Content-Type': 'application/json'})
        assert code == 200, response
        created = json.loads(response)
        session = service.start(created['id'])
        code, _, response = request(server, 'POST', '/api/v1/command', body=command_body('study', ['session', '--course', 'POL 2103', '--session', session['id']]), headers={'Content-Type': 'application/json'})
        assert code == 200, response
        assert json.loads(response)['id'] == session['id']
        assert 'answer' not in json.loads(response)['items'][0]


def test_browser_study_payload_can_exceed_normal_argument_limit_without_widening_other_commands(tmp_path):
    from academia_os.web import CommandResult
    from tests.test_web import running_server, request, command_body
    received = []
    def runner(command, args):
        received.append((command, args)); return CommandResult(0, '{}', '')
    with running_server(tmp_path, runner=runner) as server:
        for command, expected in [('study', 200), ('status', 400)]:
            code, _, _ = request(server, 'POST', '/api/v1/command', body=command_body(command, ['--payload-json', 'x' * 2000]), headers={'Content-Type': 'application/json'})
            assert code == expected
    assert len(received) == 1


def test_codex_runtime_prefers_newer_installed_client_and_filters_internal_models(monkeypatch, tmp_path):
    from academia_os.study.providers import codex_runtime
    old_dir, new_dir = tmp_path / 'old', tmp_path / 'new'
    for directory in (old_dir, new_dir):
        directory.mkdir(); binary = directory / 'codex'; binary.write_text('synthetic'); binary.chmod(0o755)
    monkeypatch.delenv('ACADEMIA_CODEX_CLI', raising=False)
    monkeypatch.setattr('academia_os.study.providers.shutil.which', lambda name: str(old_dir / 'codex'))
    monkeypatch.setattr('academia_os.study.providers.os.get_exec_path', lambda: [str(old_dir), str(new_dir)])
    def run(command, **kwargs):
        if command[-1] == '--version':
            version = '0.139.0' if command[0] == str(old_dir / 'codex') else '0.159.0-alpha.12.1'
            return SimpleNamespace(returncode=0, stdout=f'codex-cli {version}')
        assert command[0] == str(new_dir / 'codex')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'models': [
            {'slug': 'hidden-reviewer', 'visibility': 'hide', 'priority': 0},
            {'slug': 'current-model', 'visibility': 'list', 'priority': 1}]}))
    monkeypatch.setattr('academia_os.study.providers.subprocess.run', run)
    result = codex_runtime()
    assert result['executable'] == str(new_dir / 'codex')
    assert result['recommended_model'] == 'current-model'
    assert [item['id'] for item in result['models']] == ['current-model']


def test_codex_model_only_replaces_unavailable_inherited_defaults(monkeypatch):
    from academia_os.study.providers import codex_model
    runtime = {'models': [{'id': 'current-model'}, {'id': 'other-model'}], 'recommended_model': 'current-model'}
    monkeypatch.setattr('academia_os.study.providers.configured_codex_model', lambda: 'retired-model')
    model, notice = codex_model(runtime)
    assert model == 'current-model' and 'retired-model' in notice
    assert codex_model(runtime, 'other-model') == ('other-model', None)
    with pytest.raises(ValueError, match='not in this Codex client'):
        codex_model(runtime, 'retired-model')
    monkeypatch.setattr('academia_os.study.providers.configured_codex_model', lambda: 'other-model')
    assert codex_model(runtime) == ('other-model', None)


def test_codex_explicit_client_override_is_honored(monkeypatch, tmp_path):
    from academia_os.study.providers import codex_runtime
    binary = tmp_path / 'selected-codex'; binary.write_text('synthetic'); binary.chmod(0o755)
    monkeypatch.setenv('ACADEMIA_CODEX_CLI', str(binary))
    monkeypatch.setattr('academia_os.study.providers.shutil.which', lambda value: str(binary))
    seen = []
    def run(command, **kwargs):
        seen.append(command[0])
        return SimpleNamespace(returncode=0, stdout='codex-cli 0.139.0') if command[-1] == '--version' else SimpleNamespace(returncode=1, stdout='')
    monkeypatch.setattr('academia_os.study.providers.subprocess.run', run)
    result = codex_runtime()
    assert result['executable'] == str(binary)
    assert seen == [str(binary), str(binary)]
