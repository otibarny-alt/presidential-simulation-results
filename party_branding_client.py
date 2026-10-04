"""Read-only client for the central nomination-system party branding API."""
import json, os, threading, time
from urllib.parse import urljoin
from urllib.request import Request, urlopen

DEFAULT={"code":"ODM","name":"Orange Democratic Movement","abbreviation":"ODM",
         "slogan":"Tuko Tayari","membership_prefix":"ODM","primary":"#ef7d00",
         "secondary":"#111111","accent":"#fff2df","header_url":""}
_CACHE={"at":0.0,"brand":dict(DEFAULT)}
_LOCK=threading.Lock()

def _api_url():
 direct=os.getenv("PARTY_BRANDING_API_URL","").strip()
 if direct:return direct
 base=(os.getenv("VOTING_SIMULATION_ADMIN_URL","").strip()
       or os.getenv("SIMULATION_BASE_URL","").strip()).rstrip("/")
 return base+"/api/party-branding" if base else ""

def get_brand(force=False):
 now=time.time()
 if not force and now-_CACHE["at"]<15:return dict(_CACHE["brand"])
 with _LOCK:
  if not force and now-_CACHE["at"]<15:return dict(_CACHE["brand"])
  value=dict(_CACHE["brand"] or DEFAULT);url=_api_url()
  if url:
   try:
    req=Request(url,headers={"Accept":"application/json","User-Agent":"NominationBranding/1.0"})
    with urlopen(req,timeout=4) as response:data=json.loads(response.read().decode("utf-8"))
    remote=dict(data.get("brand") or {})
    value={**DEFAULT,**remote,"header_url":str(data.get("header_url") or remote.get("header_url") or "")}
   except Exception:
    pass
  _CACHE.update(at=now,brand=value)
  return dict(value)

def register_party_branding(app):
 @app.context_processor
 def inject_party_brand():return {"party_brand":get_brand()}

 @app.after_request
 def apply_party_brand(response):
  ctype=str(response.headers.get("Content-Type") or "").lower()
  if response.direct_passthrough or "text/html" not in ctype:return response
  try:
   b=get_brand();html=response.get_data(as_text=True);header=b.get("header_url","")
   if header:
    for old in ("/static/odm_screen_header.png","/static/odm_report_header.png","/static/odm_pdf_header.jpg"):
     html=html.replace(old,header)
   replacements={"Orange Democratic Movement":b["name"],"ODM Membership":b["abbreviation"]+" Membership",
    "ODM membership":b["abbreviation"]+" membership","ODM registration":b["abbreviation"]+" registration",
    "ODM 2027":b["abbreviation"]+" 2027","Tuko Tayari":b["slogan"]}
   payload=json.dumps(replacements)
   addon=f'''<style id="party-brand-theme">:root{{--party-primary:{b['primary']};--party-secondary:{b['secondary']};--party-accent:{b['accent']}}}header{{border-bottom-color:var(--party-primary)!important}}button,.btn,.button{{border-color:var(--party-primary)!important}}</style><script id="party-brand-text">(()=>{{const r={payload};const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;while(n=w.nextNode()){{if(['SCRIPT','STYLE','TEXTAREA','OPTION'].includes(n.parentElement?.tagName))continue;let v=n.nodeValue;for(const [a,z] of Object.entries(r))v=v.split(a).join(z);n.nodeValue=v}}}})();</script>'''
   html=html.replace("</head>",addon+"</head>");response.set_data(html)
   response.headers["Content-Length"]=str(len(response.get_data()))
  except Exception:app.logger.exception("Unable to apply shared party branding")
  return response
 return app
