import os,tempfile,unittest,asyncio,gzip,zlib,json
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
os.environ['DATA_DIR']=tempfile.mkdtemp()
import httpx
from app.net import Net,ConnectorError,RateLimited
from app import core,apify_settings as cfg,engine
from app.connectors import ted,germany
from app.main import app
from fastapi.testclient import TestClient
class Wire(httpx.AsyncByteStream):
 def __init__(self,b):self.b=b
 async def __aiter__(self):
  for i in range(0,len(self.b),7):yield self.b[i:i+7]
class TransportTests(unittest.IsolatedAsyncioTestCase):
 async def request(self,body,encoding=None,status=200,cap=1000000):
  def handler(req):
   headers={'Content-Type':'application/json'}
   if encoding:headers['Content-Encoding']=encoding
   return httpx.Response(status,headers=headers,stream=Wire(body))
  n=Net();n.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
  try:return await n.request('GET','https://fixture.invalid/data',cap=cap)
  finally:await n.client.aclose()
 async def test_gzip_single_decode(self):
  r=await self.request(gzip.compress(b'{"ok":true}'),'gzip');self.assertTrue(r.json()['ok']);self.assertNotIn('content-encoding',r.headers)
 async def test_deflate_single_decode(self):
  r=await self.request(zlib.compress(b'{"ok":true}'),'deflate');self.assertTrue(r.json()['ok'])
 async def test_plain(self):self.assertEqual((await self.request(b'{}')).json(),{})
 async def test_decoded_cap(self):
  with self.assertRaisesRegex(ConnectorError,'resource cap'):await self.request(gzip.compress(b'x'*10000),'gzip',cap=100)
 async def test_429(self):
  with self.assertRaises(RateLimited):await self.request(b'{}',status=429)
 async def test_full_error_body(self):
  b=json.dumps({'message':'x'*30000+'publication-number'}).encode()
  with self.assertRaises(ConnectorError) as c:await self.request(b,status=400)
  self.assertIn('publication-number',c.exception.body)
 async def test_identity_retry(self):
  calls=[]
  def handler(req):
   calls.append(req.headers.get('accept-encoding'))
   if len(calls)==1:return httpx.Response(200,headers={'Content-Encoding':'gzip'},stream=Wire(b'not gzip'))
   return httpx.Response(200,stream=Wire(b'{}'))
  n=Net();n.client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
  try:self.assertEqual((await n.request('GET','https://fixture.invalid')).json(),{})
  finally:await n.client.aclose()
  self.assertEqual(calls[-1],'identity');self.assertEqual(len(calls),2)
 async def test_ted_currency_field(self):
  self.assertIn('estimated-value-cur-proc',ted.FIELDS)
  t=ted.parse({'publication-number':'1-2026','estimated-value-proc':5,'estimated-value-cur-proc':'EUR'})
  self.assertEqual(t.currency,'EUR')
 async def test_ted_schema_fallback(self):
  class N:
   calls=0
   async def json(self,url,**kw):
    self.calls+=1
    if self.calls==1:raise ConnectorError('HTTP 400',body=json.dumps({'message':"Parameter 'fields' contains unsupported value (supported values are: publication-number,notice-title,organisation-country-buyer,publication-date)"}))
    return {'notices':[]}
  _,stats=await ted.fetch(N(),['POL'],core.now(),{'pages':1})
  self.assertIn('publication-number',stats['reduced_fields'])
 async def test_ted_timeout_not_success(self):
  class N:
   async def json(self,*a,**kw):return {'timedOut':True,'notices':[]}
  with self.assertRaisesRegex(ConnectorError,'timed out'):await ted.fetch(N(),['POL'],core.now(),{'pages':1})
 async def test_german_yesterday(self):
  fixed=datetime(2026,10,15,12,tzinfo=timezone.utc);days=[]
  class N:
   async def request(self,*a,**kw):
    days.append(kw['params']['pubDay']);return httpx.Response(200,content=b'zip',request=httpx.Request('GET','https://fixture.invalid'))
  with patch.object(germany,'now',return_value=fixed),patch.object(germany,'parse_zip',return_value=([],{'records':0})):
   _,s=await germany.fetch(N(),['DEU'],fixed-timedelta(days=30),{'days':7})
  self.assertEqual(days[0],'2026-10-14');self.assertEqual(days[-1],'2026-10-08');self.assertTrue(s['current_day_excluded'])
 async def test_german_today_no_request(self):
  fixed=datetime(2026,10,15,12,tzinfo=timezone.utc)
  class N:
   async def request(self,*a,**kw):raise AssertionError('Must not request today')
  with patch.object(germany,'now',return_value=fixed):
   _,s=await germany.fetch(N(),['DEU'],fixed,{'days':7})
  self.assertEqual(s['requested_archive_days'],0)
class SettingsTests(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,{'ADMIN_TOKEN':'admin-fixture','APIFY_API_TOKEN':'','APIFY_ACTOR_ID':'','APIFY_INPUT_JSON':''});self.env.start();cfg.delete();engine.JOB['running']=False
  self.c=TestClient(app);self.h={'X-Admin-Token':'admin-fixture'};self.d={'token':'synthetic-fixture-token','actor_id':'owner~actor','input_json':'{}'}
 def tearDown(self):self.env.stop()
 def test_auth(self):
  self.assertEqual(self.c.get('/api/settings/apify').status_code,401)
  self.assertEqual(self.c.post('/api/settings/apify',data=self.d).status_code,401)
  os.environ.pop('ADMIN_TOKEN');self.assertEqual(self.c.get('/api/settings/apify').status_code,403)
 def test_encryption_and_no_disclosure(self):
  self.assertEqual(self.c.post('/api/settings/apify',data=self.d,headers=self.h).status_code,200)
  with core.connect() as c:v=c.execute("SELECT value FROM config WHERE key='apify_encrypted'").fetchone()[0]
  self.assertNotIn(self.d['token'],v)
  r=self.c.get('/api/settings/apify',headers=self.h);self.assertNotIn(self.d['token'],r.text);self.assertEqual(r.headers['cache-control'],'no-store');self.assertEqual(r.json()['missing'],[])
  self.d['token']='';self.assertEqual(self.c.post('/api/settings/apify',data=self.d,headers=self.h).status_code,200)
  self.assertEqual(cfg.effective()['APIFY_API_TOKEN'],'synthetic-fixture-token')
 def test_validation_delete(self):
  self.d['input_json']='[]';self.assertEqual(self.c.post('/api/settings/apify',data=self.d,headers=self.h).status_code,400)
  self.assertEqual(self.c.post('/api/settings/apify/delete',headers=self.h).status_code,200)
  self.assertEqual(len(cfg.public()['missing']),3)
 def test_lock_and_origin(self):
  engine.JOB['running']=True;self.assertEqual(self.c.post('/api/settings/apify',data=self.d,headers=self.h).status_code,409);engine.JOB['running']=False
  self.assertEqual(self.c.post('/api/settings/apify',data=self.d,headers={**self.h,'Origin':'https://evil.invalid'}).status_code,403)
 def test_clear_label(self):self.assertNotIn('built-in method',self.c.get('/').text)
if __name__=='__main__':unittest.main(verbosity=2)
