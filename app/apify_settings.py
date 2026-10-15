import os,json,re
from cryptography.fernet import Fernet,InvalidToken
from app import core
KEYS=('APIFY_API_TOKEN','APIFY_ACTOR_ID','APIFY_INPUT_JSON')
def cipher():
 key=os.getenv('SETTINGS_ENCRYPTION_KEY','')
 if not key:
  p=core.DATA/'.settings.key'
  try:fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  except FileExistsError:key=p.read_text().strip()
  else:
   key=Fernet.generate_key().decode()
   with os.fdopen(fd,'w') as f:f.write(key)
 try:return Fernet(key.encode())
 except (ValueError,TypeError):raise ValueError('Invalid SETTINGS_ENCRYPTION_KEY') from None
def stored():
 with core.connect() as c:r=c.execute("SELECT value FROM config WHERE key='apify_encrypted'").fetchone()
 if not r:return {}
 try:return json.loads(cipher().decrypt(r[0].encode()))
 except (InvalidToken,ValueError):raise ValueError('Cannot decrypt settings; restore original key') from None
def effective():
 s=stored();cfg={k:s.get(k) or os.getenv(k,'') for k in KEYS}
 if cfg[KEYS[0]]:core.RUNTIME_SECRETS.add(cfg[KEYS[0]])
 return cfg
def public():
 c=effective()
 return {'token_configured':bool(c[KEYS[0]]),'actor_id':c[KEYS[1]],'input_json':c[KEYS[2]],'configured':all(c.values()),'missing':[k for k in KEYS if not c[k]]}
def save(token,actor,input_json):
 token=token.strip();actor=actor.strip()
 if not re.fullmatch(r'[A-Za-z0-9_~-]+',actor):raise ValueError('Actor ID must be ID or username~actor-name')
 if len(input_json)>100000:raise ValueError('Input JSON too large')
 try:p=json.loads(input_json)
 except ValueError:raise ValueError('Invalid Input JSON') from None
 if not isinstance(p,dict):raise ValueError('Input JSON must be an object')
 if len(token)>4096 or any(x.isspace() for x in token):raise ValueError('Invalid token format')
 token=token or effective()[KEYS[0]]
 if not token:raise ValueError('Enter Apify API Token')
 c=dict(zip(KEYS,(token,actor,json.dumps(p,ensure_ascii=False))))
 v=cipher().encrypt(json.dumps(c,ensure_ascii=False).encode()).decode()
 with core.connect() as db:db.execute('INSERT OR REPLACE INTO config VALUES (?,?)',('apify_encrypted',v))
 core.RUNTIME_SECRETS.add(token)
def delete():
 with core.connect() as c:c.execute("DELETE FROM config WHERE key='apify_encrypted'")
