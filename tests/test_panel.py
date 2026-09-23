import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch,AsyncMock
from aiohttp.test_utils import TestClient,TestServer
from t6_kvm import panel
from kvmd.crypto import KvmdHtpasswdFile
import base64

class PanelTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  h=KvmdHtpasswdFile(str(self.root/'htpasswd'),new=True);h.set_password('tester','initial');h.save()
  (self.root/'streamer.toml').write_text('bitrate_kbps = 20000')
  (self.root/'main.yaml').write_text('h264_bitrate: {default: 20000, min: 100}')
  (self.root/'vncpasswd').write_text('initial')
  self.config=patch.object(panel,'CONFIG',self.root);self.config.start()
  app=panel.web.Application(middlewares=[panel.auth]);app.router.add_get('/',panel.index);app.router.add_post('/api/settings',panel.update)
  self.client=TestClient(TestServer(app));await self.client.start_server()
 def headers(self,password='initial',user='tester'):
  return {'Authorization':'Basic '+base64.b64encode((user+':'+password).encode()).decode(),'X-T6-Panel':'1'}
 async def asyncTearDown(self):
  await self.client.close();self.config.stop();self.tmp.cleanup()
 async def test_auth_and_csrf(self):
  self.assertEqual((await self.client.get('/')).status,401)
  self.assertEqual((await self.client.get('/',headers=self.headers('wrong'))).status,401)
  self.assertEqual((await self.client.get('/',headers=self.headers())).status,200)
  headers=self.headers();headers['Origin']='http://unrelated.invalid'
  self.assertEqual((await self.client.post('/api/settings',headers=headers,json={})).status,403)
 async def test_invalid_bitrate_preserves_config(self):
  r=await self.client.post('/api/settings',headers=self.headers(),json={'bitrate_kbps':99999,'continuous':False,'username':'tester'})
  self.assertEqual(r.status,400);self.assertEqual((self.root/'streamer.toml').read_text(),'bitrate_kbps = 20000')

 async def test_save_account_mode_and_bitrate(self):
  with patch.object(panel,'BACKUPS',self.root/'backups'),patch.object(panel,'restart',new=AsyncMock()) as restart:
   r=await self.client.post('/api/settings',headers=self.headers(),json={'bitrate_kbps':12000,'continuous':True,'username':'newuser','password':'newpass'})
   self.assertEqual(r.status,200)
   import asyncio
   await asyncio.sleep(.01)
   restart.assert_awaited_once_with(True)
  self.assertEqual(json.loads((self.root/'panel.json').read_text()),{'continuous':True})
  self.assertIn('12000',(self.root/'streamer.toml').read_text())
  self.assertIn('default: 12000',(self.root/'main.yaml').read_text())
  self.assertEqual((await self.client.get('/',headers=self.headers())).status,401)
  self.assertEqual((await self.client.get('/',headers=self.headers('newpass','newuser'))).status,200)
  self.assertEqual((self.root/'vncpasswd').read_text().strip(),'newpass')
