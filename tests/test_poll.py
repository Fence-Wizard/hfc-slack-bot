import importlib
import sys
import types
import os
import json
import pytest

class FakeApp:
    def __init__(self, *args, **kwargs):
        pass
    def command(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator
    def action(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator
    def view(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

class DummyFlask:
    def __init__(self, *args, **kwargs):
        pass
    def route(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

class FakeHandler:
    def __init__(self, app):
        self.app = app

@pytest.fixture
def main_module(monkeypatch):
    # stub external modules required by main
    fake_flask = types.SimpleNamespace(Flask=DummyFlask, request=None)
    fake_bolt = types.SimpleNamespace(App=FakeApp)
    fake_adapter_flask = types.SimpleNamespace(SlackRequestHandler=lambda app: FakeHandler(app))
    fake_bolt_adapter = types.SimpleNamespace(flask=fake_adapter_flask)

    monkeypatch.setitem(sys.modules, 'flask', fake_flask)
    monkeypatch.setitem(sys.modules, 'slack_bolt', fake_bolt)
    monkeypatch.setitem(sys.modules, 'slack_bolt.adapter', fake_bolt_adapter)
    monkeypatch.setitem(sys.modules, 'slack_bolt.adapter.flask', fake_adapter_flask)

    monkeypatch.setenv('SLACK_BOT_TOKEN', 'x')
    monkeypatch.setenv('SLACK_SIGNING_SECRET', 'y')

    root_path = os.path.dirname(os.path.dirname(__file__))
    monkeypatch.syspath_prepend(root_path)

    if 'main' in sys.modules:
        del sys.modules['main']
    module = importlib.import_module('main')
    return module

@pytest.fixture
def poll_setup(main_module):
    pd = main_module.poll_data
    pd.update({
        'type': 'vote',
        'question': 'Choose',
        'options': ['A', 'B'],
        'feedback_questions': [],
        'votes': {},
        'tallies': {0: 0, 1: 0},
        'feedback_responses': [],
        'creator_id': 'Ucreator',
        'channel_id': 'C1',
        'multi': False,
        'active': True,
    })
    return pd

class MockSlackClient:
    def __init__(self):
        self.messages = []
    def chat_postEphemeral(self, channel=None, user=None, text=None):
        self.messages.append({'channel': channel, 'user': user, 'text': text})


def test_handle_vote_records_and_rejects(main_module, poll_setup):
    client = MockSlackClient()
    ack_calls = []
    def ack():
        ack_calls.append(True)

    body = {'channel': {'id': 'C1'}, 'user': {'id': 'U1'}}
    action = {'action_id': 'vote_1'}

    # first vote
    main_module.handle_vote(ack, body, action, client)
    assert poll_setup['votes']['U1'] == 1
    assert poll_setup['tallies'][1] == 1
    assert 'Vote recorded' in client.messages[-1]['text']

    # second vote should be rejected
    main_module.handle_vote(ack, body, action, client)
    assert poll_setup['tallies'][1] == 1  # unchanged
    assert client.messages[-1]['text'] == '✅ You\u2019ve already voted!'
    assert len(ack_calls) == 2


def test_handle_vote_multi_allows_multiple(main_module, poll_setup):
    poll_setup['multi'] = True
    client = MockSlackClient()
    def ack():
        pass

    body = {'channel': {'id': 'C1'}, 'user': {'id': 'U1'}}
    action0 = {'action_id': 'vote_0'}
    action1 = {'action_id': 'vote_1'}

    main_module.handle_vote(ack, body, action0, client)
    main_module.handle_vote(ack, body, action1, client)

    assert poll_setup['tallies'][0] == 1
    assert poll_setup['tallies'][1] == 1
    assert poll_setup['votes']['U1'] == {0, 1}


def test_handle_poll_step1_ack_update(main_module):
    payloads = []
    def ack(**kwargs):
        payloads.append(kwargs)

    body = {'trigger_id': 'T1'}
    view = {
        'private_metadata': json.dumps({'channel': 'C1', 'user': 'U1'}),
        'state': {
            'values': {
                'type_block': {'poll_type': {'selected_option': {'value': 'vote'}}},
                'question_block': {'question_input': {'value': 'Q'}},
                'visibility_block': {'visibility_select': {'selected_option': {'value': 'public'}}},
            }
        }
    }

    main_module.handle_poll_step1(ack, body, view, client=object())

    assert payloads
    assert payloads[0]['response_action'] == 'update'
    assert payloads[0]['view']['callback_id'] == 'submit_poll'

