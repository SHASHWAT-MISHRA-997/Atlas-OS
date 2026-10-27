"""Tests for the ATLAS PC helper. Run: python -m unittest discover pc-helper  (no Windows needed: FakePC)."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import atlas_helper as h

ORIGIN = 'https://atlas-os-sm.netlify.app'


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        for f in h.USER_FOLDERS:
            (self.home / f).mkdir()
        self.pc = h.FakePC(self.home)
        self.helper = h.Helper(self.pc, self.home / 'cfg.json', say=lambda s: None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_action(self, _action, /, **args):
        return self.helper.run(_action, args)

    def test_open_app_finds_start_menu_names_and_aliases(self):
        self.assertEqual(self.run_action('open_app', name='notepad')['message'], 'Opened Notepad.')
        self.run_action('open_app', name='chrome')
        self.run_action('open_app', name='VS code')
        self.assertEqual([d[1] for d in self.pc.done], ['notepad.exe', 'chrome.exe', 'code.exe'])
        self.assertEqual(self.pc.asked, [], 'opening an app needs no Allow box')

    def test_shells_and_unknown_apps_are_refused(self):
        for bad in ('PowerShell', 'cmd', 'Command Prompt', 'Windows Terminal', 'regedit', 'Uninstall Spotify'):
            with self.assertRaises(h.ActionError, msg=bad):
                self.run_action('open_app', name=bad)
        with self.assertRaisesRegex(h.ActionError, 'No app called'):
            self.run_action('open_app', name='photoshop')
        with self.assertRaisesRegex(h.ActionError, 'Unknown action'):
            self.run_action('run_command', command='del *')
        with self.assertRaisesRegex(h.ActionError, 'Unknown action'):
            self.run_action('__init__')
        self.assertEqual(self.pc.done, [])

    def test_real_app_list_never_contains_shells(self):
        pc = h.WindowsPC()
        pc._apps = None
        names = [n for n, _ in pc.apps()]
        self.assertFalse([n for n in names if h.BLOCKED_APP.search(n)])

    def test_urls_and_search(self):
        self.run_action('open_url', url='https://example.com/a')
        for bad in ('javascript:alert(1)', 'file:///C:/Windows/System32/cmd.exe', 'ms-settings:', 'example.com'):
            with self.assertRaises(h.ActionError, msg=bad):
                self.run_action('open_url', url=bad)
        self.run_action('web_search', query='lofi beats & chill', site='youtube')
        self.assertEqual(self.pc.done[-1], ('open_url', 'https://www.youtube.com/results?search_query=lofi+beats+%26+chill'))
        with self.assertRaises(h.ActionError):
            self.run_action('web_search', query='x', site='evil.com')

    def test_typing_and_risky_keys_ask_first_and_no_means_no(self):
        self.pc.approve = False
        r = self.run_action('type_text', text='hello')
        self.assertFalse(r['ok'])
        self.assertTrue(r['denied'])
        self.assertIn('hello', self.pc.asked[-1])
        self.assertIn('Untitled - Notepad', self.pc.asked[-1], 'the Allow box names the window')
        self.assertFalse(self.run_action('press_keys', keys='ctrl+s')['ok'])
        self.assertFalse(self.run_action('window', action='close')['ok'])
        self.assertEqual(self.pc.done, [], 'nothing happens after No')
        self.pc.approve = True
        self.assertTrue(self.run_action('type_text', text='hello\nworld')['ok'])
        self.assertEqual(self.pc.done[-1], ('type_text', 'hello\nworld'))

    def test_safe_keys_need_no_prompt_and_blocked_keys_never_run(self):
        self.run_action('press_keys', keys='Alt + Tab')
        self.run_action('press_keys', keys='pagedown')
        self.run_action('window', action='show_desktop')
        self.assertEqual(self.pc.asked, [])
        self.assertEqual(self.pc.done, [('press', ('alt', 'tab')), ('press', ('pagedown',)), ('press', ('win', 'd'))])
        for bad in ('win+r', 'Win + X', 'ctrl+alt+del', 'ctrl+shift+esc', 'shift+alt+ctrl+delete'):
            with self.assertRaises(h.ActionError, msg=bad):
                self.run_action('press_keys', keys=bad)
        with self.assertRaises(h.ActionError):
            self.run_action('press_keys', keys='ctrl+alt+shift+win+a')
        with self.assertRaises(h.ActionError):
            self.run_action('press_keys', keys='hyper+q')

    def test_media_steps(self):
        self.assertEqual(self.run_action('media', key='volume_up', steps=10)['message'], 'Volume up (20%).')
        self.run_action('media', key='play_pause', steps=9)
        self.assertEqual(self.pc.done, [('media', 'volume_up', 10), ('media', 'play_pause', 1)])
        for bad in (0, 51, '5', True):
            with self.assertRaises(h.ActionError):
                self.run_action('media', key='volume_up', steps=bad)

    def test_files_stay_inside_the_user_folder_and_programs_never_open(self):
        doc = self.home / 'Documents' / 'Budget 2026.xlsx'
        doc.write_text('x')
        (self.home / 'Downloads' / 'setup.exe').write_text('x')
        (self.home / 'AppData').mkdir()
        (self.home / 'AppData' / 'secret.txt').write_text('x')
        found = self.run_action('find_files', query='budget')['files']
        self.assertEqual(found, [str(doc)])
        self.run_action('open_file', path=str(doc))
        self.assertEqual(self.pc.done[-1], ('launch', str(doc.resolve())))
        for bad in (str(self.home / 'Downloads' / 'setup.exe'), str(self.home / 'AppData' / 'secret.txt'), '/etc/passwd',
                    str(self.home / 'Documents' / '..' / '..' / 'x.txt'), str(self.home / 'Documents' / 'missing.pdf')):
            with self.assertRaises(h.ActionError, msg=bad):
                self.run_action('open_file', path=bad)
        self.run_action('open_folder', folder='downloads')
        self.assertEqual(self.pc.done[-1], ('launch', str(self.home / 'Downloads')))
        with self.assertRaises(h.ActionError):
            self.run_action('open_folder', folder='/')

    def test_notes_never_overwrite(self):
        a = self.run_action('write_note', title='Shopping/../list', text='milk')['path']
        b = self.run_action('write_note', title='Shopping/../list', text='eggs')['path']
        self.assertNotEqual(a, b)
        self.assertEqual(Path(a).parent, self.home / 'Documents' / 'ATLAS Notes')
        self.assertEqual(Path(a).read_text(encoding='utf-8'), 'milk\n')

    def test_system_info(self):
        r = self.run_action('system_info')
        self.assertEqual(r['battery'], {'percent': 80, 'charging': True})
        self.assertIn('time', r)

    def test_bad_arguments(self):
        for name, args in [('open_app', {}), ('open_app', {'name': 5}), ('open_app', {'name': 'x' * 81}), ('type_text', {'text': 'x' * 2001})]:
            with self.assertRaises(h.ActionError):
                self.helper.run(name, args)
        with self.assertRaises(h.ActionError):
            self.helper.run('open_app', ['notepad'])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.pc = h.FakePC(self.home)
        self.helper = h.Helper(self.pc, self.home / 'cfg.json', {'http://localhost:8888'}, say=lambda s: None)
        self.server = h.serve(self.helper, 0)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, origin=ORIGIN, token=None, host=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Host': host or f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        if token:
            headers['Authorization'] = 'Bearer ' + token
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if data else {}), dict(r.getheaders())

    def pair(self, origin=ORIGIN):
        code = self.helper.new_code()
        status, body, _ = self.call('POST', '/pair', {'code': code[:3] + ' ' + code[3:]}, origin=origin)
        self.assertEqual(status, 200, body)
        return body['token']

    def test_pair_then_act(self):
        self.assertEqual(self.call('POST', '/action', {'name': 'open_app', 'args': {'name': 'notepad'}})[0], 401)
        token = self.pair()
        status, body, headers = self.call('POST', '/action', {'name': 'open_app', 'args': {'name': 'notepad'}}, token=token)
        self.assertEqual((status, body['ok']), (200, True))
        self.assertEqual(headers['Access-Control-Allow-Origin'], ORIGIN)
        self.assertEqual(self.pc.done, [('launch', 'notepad.exe')])
        self.assertIn('type_text', self.call('GET', '/status', token=token)[1]['actions'])
        self.assertTrue(self.call('GET', '/hello', token=token)[1]['paired'])
        # The token is stored only as a hash, and survives a restart.
        saved = (self.home / 'cfg.json').read_text()
        self.assertNotIn(token, saved)
        self.assertTrue(h.Helper(self.pc, self.home / 'cfg.json').token_ok('Bearer ' + token, ORIGIN))
        # Refused actions come back as a readable message, not a crash.
        status, body, _ = self.call('POST', '/action', {'name': 'open_app', 'args': {'name': 'cmd'}}, token=token)
        self.assertEqual((status, body['ok']), (200, False))
        self.assertIn('shells', body['message'])
        self.assertEqual(self.call('POST', '/unpair', {}, token=token)[0], 200)
        self.assertEqual(self.call('POST', '/action', {'name': 'lock_pc'}, token=token)[0], 401)

    def test_other_sites_and_rebinding_are_refused(self):
        token = self.pair()
        for origin in ('https://evil.example', 'https://atlas-os-sm.netlify.app.evil.example', 'null', ''):
            self.assertEqual(self.call('POST', '/action', {'name': 'lock_pc'}, origin=origin, token=token)[0], 403, origin)
        self.assertEqual(self.call('GET', '/hello', origin='https://evil.example')[0], 403)
        self.assertEqual(self.call('POST', '/action', {'name': 'lock_pc'}, token=token, host='attacker.example:' + str(self.port))[0], 421)
        # A token works only from the site it was paired with.
        self.assertEqual(self.call('POST', '/action', {'name': 'lock_pc'}, origin='http://localhost:8888', token=token)[0], 401)
        self.assertEqual(self.call('POST', '/action', {'name': 'lock_pc'}, origin='https://deploy-preview-3--atlas-os-sm.netlify.app', token=token)[0], 401)
        self.assertEqual(self.pc.done, [])

    def test_preflight_allows_the_local_network_request(self):
        status, _, headers = self.call('OPTIONS', '/action')
        self.assertEqual(status, 204)
        self.assertEqual(headers['Access-Control-Allow-Private-Network'], 'true')
        self.assertIn('Authorization', headers['Access-Control-Allow-Headers'])

    def test_wrong_codes(self):
        self.helper.new_code()
        wrong = '000000' if self.helper.code != '000000' else '111111'
        for i in range(h.MAX_CODE_TRIES):
            status, body, _ = self.call('POST', '/pair', {'code': wrong})
            self.assertEqual(status, 400)
        self.assertIn('Too many', body['error'])
        self.assertEqual(self.helper.code, '', 'the code is gone after too many tries')
        code = self.helper.new_code()
        self.assertEqual(self.call('POST', '/pair', {'code': code})[0], 200)
        self.assertEqual(self.call('POST', '/pair', {'code': code})[0], 400, 'a code works once')

    def test_bodies(self):
        token = self.pair()
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        c.request('POST', '/action', 'x' * (h.MAX_BODY + 1), {'Host': f'127.0.0.1:{self.port}', 'Origin': ORIGIN, 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
        self.assertEqual(c.getresponse().status, 413)
        c.close()
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        c.request('POST', '/action', '{}', {'Host': f'127.0.0.1:{self.port}', 'Origin': ORIGIN, 'Content-Type': 'text/plain', 'Authorization': 'Bearer ' + token})
        self.assertEqual(c.getresponse().status, 415, 'a plain form post cannot reach it')
        c.close()


if __name__ == '__main__':
    unittest.main()
