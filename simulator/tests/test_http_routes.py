"""Exercise real HTTP parsing/handlers in memory, without opening a TCP port.

This complements the live APITests; it does not verify TCP or browser rendering.
"""
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from simulator.engine import World
from simulator.server import Handler


class Connection:
    def __init__(self, data):
        self.input=io.BytesIO(data)
        self.output=bytearray()

    def makefile(self,*args,**kwargs):
        return self.input

    def sendall(self,data):
        self.output.extend(data)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.world=World()
        self.server=SimpleNamespace(world=self.world,server_port=8767,publisher='test',
            camera_meta=lambda:dict(ready=False,width=640,height=480))

    def request(self,path,data=None,headers=None):
        body=b'' if data is None else json.dumps(data).encode()
        request_headers={'Host':'127.0.0.1:8767','Connection':'close',
                         'Content-Type':'application/json','Content-Length':str(len(body)),**(headers or {})}
        raw=f"{'GET' if data is None else 'POST'} {path} HTTP/1.1\r\n"
        raw+=''.join(f'{k}: {v}\r\n' for k,v in request_headers.items())
        connection=Connection(raw.encode()+b'\r\n'+body)
        Handler(connection,('127.0.0.1',12345),self.server)
        header,payload=bytes(connection.output).split(b'\r\n\r\n',1)
        status=int(header.split(b' ',2)[1])
        return status,json.loads(payload)

    def test_default_start_and_autopilot_toggle(self):
        status,result=self.request('/api/game/start',{})
        self.assertEqual(status,200)
        self.assertEqual(result['game']['mode'],'tag')
        self.assertTrue(result['game']['auto_chase'])
        self.assertEqual(self.request('/api/game/auto',{'enabled':False})[0],200)
        self.assertFalse(self.world.game['auto_chase'])
        self.assertEqual(self.request('/api/game/auto',{'enabled':True})[0],200)
        self.assertTrue(self.world.game['auto_chase'])

    def test_external_ai_start_and_manual_takeover(self):
        self.request('/api/game/start',{'mode':'tag','auto_chase':False})
        self.assertFalse(self.world.game['auto_chase'])
        self.request('/api/game/auto',{'enabled':True})
        status,_=self.request('/api/robot/command',{'linear_mps':.1,'seconds':.5})
        self.assertEqual(status,200)
        self.assertFalse(self.world.game['auto_chase'])

    def test_stop_disables_autopilot_and_remains_stopped(self):
        self.request('/api/game/start',{})
        self.world.tick(.02)
        self.assertEqual(self.request('/api/robot/stop',{})[0],200)
        before=dict(self.world.robot)
        for _ in range(20):self.world.tick(.02)
        self.assertEqual(self.world.robot,before)
        self.assertFalse(self.world.game['auto_chase'])

    def test_hold_and_invalid_population_are_atomic(self):
        self.request('/api/game/start',{})
        self.assertEqual(self.request('/api/game/hold',{'held':True})[0],200)
        self.assertTrue(self.world.game['held'])
        self.assertEqual(self.request('/api/world/config',{'count':8,'rate':4,'paused':True})[0],400)
        self.assertEqual(self.world.rate,1)
        self.assertFalse(self.world.paused)

    def test_legacy_mode_and_unknown_mode(self):
        self.assertEqual(self.request('/api/game/start',{'mode':'red_light'})[0],200)
        self.assertEqual(self.world.game['phase'],'approaching')
        epoch=self.world.epoch
        self.assertEqual(self.request('/api/game/start',{'mode':'unknown'})[0],400)
        self.assertEqual(self.world.epoch,epoch)

    def test_cross_origin_and_wrong_host_do_not_start_game(self):
        for headers in ({'Origin':'https://other.example'},{'Host':'other.example'}):
            self.assertEqual(self.request('/api/game/start',{},headers)[0],403)
            self.assertEqual(self.world.game['phase'],'ready')

    def test_state_exposes_synthetic_trajectory_and_tag_result(self):
        self.request('/api/game/start',{'auto_chase':False})
        self.world.children[0].update(x=0,z=self.world.robot['z']+.70)
        self.world.tick(.02)
        status,result=self.request('/api/state')
        self.assertEqual(status,200)
        self.assertEqual(result['game']['caught_ids'],[0])
        self.assertTrue(result['children'][0]['caught'])
        self.assertIn('motion_time',result['children'][1])

    def test_locally_generated_motion_asset_is_served(self):
        path=Path(__file__).parents[1]/'static/motions/childact.local.json'
        if not path.exists():self.skipTest('local ChildACT asset not built')
        status,pack=self.request('/motions/childact.local.json')
        self.assertEqual(status,200)
        self.assertEqual(pack['source']['archive_md5'],'d1d6cfe12f0221463280803c8b0eb581')
        self.assertEqual(set(pack['clips']),{'walk','jog','run'})


if __name__=='__main__':unittest.main()
