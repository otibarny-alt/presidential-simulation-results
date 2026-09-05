
import os, csv, re, time
from functools import wraps

import requests
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from dotenv import load_dotenv

BASE_DIR=os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR,".env"))

app=Flask(__name__)
app.secret_key=os.getenv("FLASK_SECRET_KEY","CHANGE-ME")

SIMULATION_BASE_URL=os.getenv("SIMULATION_BASE_URL","").rstrip("/")
SIMULATION_DASHBOARD_API_KEY=os.getenv("SIMULATION_DASHBOARD_API_KEY","").strip()
COUNTY_MAIN_FILENAME=os.getenv("COUNTY_MAIN_FILENAME","county_main.csv").strip()
AGENTS_LOGIN_FILENAME=os.getenv("AGENTS_LOGIN_FILENAME","agents_login.csv").strip()
CACHE_SECONDS=int(os.getenv("CACHE_SECONDS","3"))

AUTH_USERNAME=os.getenv("AUTH_USERNAME","").strip()
AUTH_PASSWORD_HASH=os.getenv("AUTH_PASSWORD_HASH","").strip()

_cache={"snapshot_at":0.0,"snapshot":None,"hierarchy":None,"registered":None}

def login_required(fn):
 @wraps(fn)
 def wrapped(*args,**kwargs):
  if AUTH_USERNAME and AUTH_PASSWORD_HASH and not session.get("dashboard_user"):
   if request.path.startswith("/api/"):
    return jsonify({"error":"Authentication required."}),401
   return redirect(url_for("login"))
  return fn(*args,**kwargs)
 return wrapped

@app.route("/login",methods=["GET","POST"])
def login():
 if not AUTH_USERNAME or not AUTH_PASSWORD_HASH:
  return redirect(url_for("index"))
 if request.method=="POST":
  username=request.form.get("username","").strip()
  password=request.form.get("password","")
  if username==AUTH_USERNAME and check_password_hash(AUTH_PASSWORD_HASH,password):
   session["dashboard_user"]=username
   return redirect(url_for("index"))
  flash("Invalid username or password.","error")
 return render_template("login.html")

@app.get("/logout")
def logout():
 session.clear()
 return redirect(url_for("login"))

def norm(v):
 return re.sub(r"[-_\s]+"," ",str(v or "").strip().lower()).strip()

def friendly(v):
 text=str(v or "").strip()
 return re.sub(r"\s+"," ",re.sub(r"[_-]+"," ",text)).title() if text else ""

def to_int(v):
 try:return int(float(str(v or "0").replace(",","").strip()))
 except:return 0

def load_hierarchy():
 if _cache["hierarchy"] is not None:
  return _cache["hierarchy"]
 with open(os.path.join(BASE_DIR,COUNTY_MAIN_FILENAME),encoding="utf-8-sig",errors="replace",newline="") as f:
  rows=list(csv.DictReader(f))

 counties={}
 constituencies={}
 wards={}
 stations={}
 streams={}
 for r in rows:
  kind=r.get("list_name","")
  name=r.get("name","")
  if not name: continue
  item={k:(v or "") for k,v in r.items()}
  if kind=="county":counties[norm(name)]=item
  elif kind=="constituency":constituencies[norm(name)]=item
  elif kind=="ward":wards[norm(name)]=item
  elif kind=="poll_station":stations[norm(name)]=item
  elif kind=="poll_station_stream":streams[norm(name)]=item

 expected=[]
 for skey,srow in streams.items():
  station=stations.get(norm(srow.get("poll_station_key","")),{})
  ward=wards.get(norm(station.get("ward_key","")),{})
  constituency=constituencies.get(norm(ward.get("constituency_key","")),{})
  county=counties.get(norm(constituency.get("county_key","")),{})
  expected.append({
   "county":county.get("name",""),
   "county_label":county.get("label") or friendly(county.get("name","")),
   "constituency":constituency.get("name",""),
   "constituency_label":constituency.get("label") or friendly(constituency.get("name","")),
   "ward":ward.get("name",""),
   "ward_label":ward.get("label") or friendly(ward.get("name","")),
   "poll_station":station.get("name",""),
   "poll_station_label":station.get("label") or friendly(station.get("name","")),
   "stream":srow.get("name",""),
   "stream_label":srow.get("label") or friendly(srow.get("name",""))
  })
 _cache["hierarchy"]={
  "rows":rows,"counties":counties,"constituencies":constituencies,
  "wards":wards,"stations":stations,"streams":streams,"expected":expected
 }
 return _cache["hierarchy"]

def load_registered():
 if _cache["registered"] is not None:
  return _cache["registered"]
 idx={}
 path=os.path.join(BASE_DIR,AGENTS_LOGIN_FILENAME)
 try:
  with open(path,encoding="utf-8-sig",errors="replace",newline="") as f:
   for r in csv.DictReader(f):
    stream=str(r.get("poll_station_name","") or "").strip()
    if stream:
     idx[norm(stream)]=to_int(r.get("total_registered_voters",0))
 except Exception:
  pass
 _cache["registered"]=idx
 return idx

def fetch_snapshot(force=False):
 now=time.time()
 if not force and _cache["snapshot"] is not None and now-_cache["snapshot_at"]<CACHE_SECONDS:
  return _cache["snapshot"]
 if not SIMULATION_BASE_URL or not SIMULATION_DASHBOARD_API_KEY:
  raise RuntimeError("Simulation dashboard connection is not configured.")
 r=requests.get(
  f"{SIMULATION_BASE_URL}/api/dashboard/president",
  headers={"X-Dashboard-Key":SIMULATION_DASHBOARD_API_KEY},
  timeout=45
 )
 if not r.ok:
  raise RuntimeError(f"Simulation API HTTP {r.status_code}: {r.text[:300]}")
 data=r.json()
 _cache["snapshot_at"]=now
 _cache["snapshot"]=data
 return data

def filtered_expected(county="",constituency="",ward=""):
 county_n,con_n,ward_n=norm(county),norm(constituency),norm(ward)
 result=[]
 for g in load_hierarchy()["expected"]:
  if county_n and norm(g["county"])!=county_n:continue
  if con_n and norm(g["constituency"])!=con_n:continue
  if ward_n and norm(g["ward"])!=ward_n:continue
  result.append(g)
 return result

def filtered_snapshot_streams(snapshot,county="",constituency="",ward=""):
 expected=filtered_expected(county,constituency,ward)
 allowed={norm(x["stream"]) for x in expected}
 return [x for x in snapshot.get("streams",[]) if norm(x.get("stream","")) in allowed]

def registered_for_expected(expected):
 idx=load_registered()
 return sum(idx.get(norm(x["stream"]),0) for x in expected)

def summary_payload(county="",constituency="",ward=""):
 snap=fetch_snapshot()
 expected=filtered_expected(county,constituency,ward)
 streams=filtered_snapshot_streams(snap,county,constituency,ward)
 expected_keys={norm(x["stream"]) for x in expected}
 stream_by_key={norm(x.get("stream","")):x for x in streams}

 candidate_names={}
 candidate_votes={}
 for c in snap.get("candidates",[]):
  cid=str(c.get("candidate_id",""))
  if cid:
   candidate_names[cid]=c.get("name") or cid
   candidate_votes[cid]=0

 candidate_selections=skipped=participants=0
 for row in streams:
  candidate_selections+=to_int(row.get("candidate_selections"))
  skipped+=to_int(row.get("skipped"))
  participants+=to_int(row.get("participants"))
  names=row.get("candidate_names") or {}
  for cid,n in (row.get("candidate_votes") or {}).items():
   candidate_names[cid]=names.get(cid) or candidate_names.get(cid) or cid
   candidate_votes[cid]=candidate_votes.get(cid,0)+to_int(n)

 ranked=[
  {"candidate_id":cid,"candidate":candidate_names.get(cid,cid),"votes":votes}
  for cid,votes in candidate_votes.items()
 ]
 ranked.sort(key=lambda x:(-x["votes"],x["candidate"].lower()))
 for x in ranked:
  x["share"]=round(x["votes"]/candidate_selections*100,2) if candidate_selections else 0

 opened=sum(1 for k in expected_keys if stream_by_key.get(k,{}).get("status") in {"OPEN","CLOSED"})
 closed=sum(1 for k in expected_keys if stream_by_key.get(k,{}).get("status")=="CLOSED")
 active=sum(1 for k in expected_keys if to_int(stream_by_key.get(k,{}).get("participants"))>0)
 registered=registered_for_expected(expected)
 no_participation=max(0,registered-participants)
 skip_pct=round(skipped/registered*100,2) if registered else 0
 turnout_pct=round(participants/registered*100,2) if registered else 0

 station_expected={}
 for g in expected:
  station_expected.setdefault(norm(g["poll_station"]),set()).add(norm(g["stream"]))
 complete=partial=not_started=0
 for stream_ids in station_expected.values():
  statuses=[stream_by_key.get(k,{}).get("status","NOT STARTED") for k in stream_ids]
  if statuses and all(x=="CLOSED" for x in statuses):complete+=1
  elif any(x in {"OPEN","CLOSED"} for x in statuses):partial+=1
  else:not_started+=1

 last_updated=""
 for row in streams:
  t=row.get("closed_at") or row.get("opened_at") or ""
  if t>last_updated:last_updated=t

 return {
  "filters":{"county":county,"constituency":constituency,"ward":ward},
  "candidates":ranked,
  "candidate_series":[{"candidate":x["candidate"],"votes":x["votes"]} for x in ranked],
  "totals":{
   "candidate_selections":candidate_selections,
   "skipped":skipped,
   "participants":participants,
   "registered_voters":registered,
   "not_participated":no_participation,
   "turnout_percent":turnout_pct,
   "skip_percent_registered":skip_pct
  },
  "reporting":{
   "expected_streams":len(expected_keys),
   "opened_streams":opened,
   "closed_streams":closed,
   "active_streams":active,
   "not_started_streams":max(0,len(expected_keys)-opened),
   "opening_percent":round(opened/len(expected_keys)*100,2) if expected_keys else 0,
   "polling_centres_complete":complete,
   "polling_centres_partial":partial,
   "polling_centres_not_started":not_started
  },
  "last_updated":last_updated
 }

@app.get("/")
@login_required
def index():
 return render_template("index.html")

@app.get("/api/summary")
@login_required
def api_summary():
 try:
  return jsonify(summary_payload(
   request.args.get("county",""),
   request.args.get("constituency",""),
   request.args.get("ward","")
  ))
 except Exception as exc:
  return jsonify({"error":str(exc)}),500

@app.get("/api/counties")
@login_required
def api_counties():
 hp=load_hierarchy()
 rows=[{"value":v.get("name",""),"label":v.get("label") or friendly(v.get("name",""))} for v in hp["counties"].values()]
 rows.sort(key=lambda x:x["label"])
 return jsonify(rows)

@app.get("/api/constituencies")
@login_required
def api_constituencies():
 county=norm(request.args.get("county",""))
 hp=load_hierarchy()
 rows=[]
 for v in hp["constituencies"].values():
  if norm(v.get("county_key",""))==county:
   rows.append({"value":v.get("name",""),"label":v.get("label") or friendly(v.get("name",""))})
 rows.sort(key=lambda x:x["label"])
 return jsonify(rows)

@app.get("/api/wards")
@login_required
def api_wards():
 constituency=norm(request.args.get("constituency",""))
 hp=load_hierarchy()
 rows=[]
 for v in hp["wards"].values():
  if norm(v.get("constituency_key",""))==constituency:
   rows.append({"value":v.get("name",""),"label":v.get("label") or friendly(v.get("name",""))})
 rows.sort(key=lambda x:x["label"])
 return jsonify(rows)

@app.get("/api/stream-details")
@login_required
def api_stream_details():
 county=request.args.get("county","")
 constituency=request.args.get("constituency","")
 ward=request.args.get("ward","")
 status_filter=request.args.get("status","").strip().upper()
 search=request.args.get("search","").strip().upper()
 try:page=max(1,int(request.args.get("page","1")))
 except:page=1
 try:page_size=max(25,min(500,int(request.args.get("page_size","200"))))
 except:page_size=200

 snap=fetch_snapshot()
 expected=filtered_expected(county,constituency,ward)
 live={norm(x.get("stream","")):x for x in filtered_snapshot_streams(snap,county,constituency,ward)}
 reg=load_registered()
 rows=[]
 for g in expected:
  x=live.get(norm(g["stream"]),{})
  status=x.get("status","NOT STARTED")
  if status_filter and status!=status_filter:continue
  if search:
   hay=" | ".join([g["county_label"],g["constituency_label"],g["ward_label"],g["poll_station_label"],g["stream_label"]]).upper()
   if search not in hay:continue
  rows.append({
   **g,
   "registered_voters":reg.get(norm(g["stream"]),0),
   "status":status,
   "participants":to_int(x.get("participants")),
   "candidate_selections":to_int(x.get("candidate_selections")),
   "skipped":to_int(x.get("skipped")),
   "opened_at":x.get("opened_at",""),
   "closed_at":x.get("closed_at","")
  })

 rows.sort(key=lambda x:(x["county_label"],x["constituency_label"],x["ward_label"],x["poll_station_label"],x["stream_label"]))
 total_rows=len(rows)
 total_pages=max(1,(total_rows+page_size-1)//page_size)
 page=min(page,total_pages)
 chunk=rows[(page-1)*page_size:page*page_size]
 return jsonify({"rows":chunk,"page":page,"page_size":page_size,"total_rows":total_rows,"total_pages":total_pages})

@app.get("/api/recent-streams")
@login_required
def api_recent_streams():
 snap=fetch_snapshot()
 county=request.args.get("county","")
 constituency=request.args.get("constituency","")
 ward=request.args.get("ward","")
 limit=min(max(to_int(request.args.get("limit",50)),1),100)
 rows=filtered_snapshot_streams(snap,county,constituency,ward)
 rows=sorted(rows,key=lambda x:(x.get("closed_at") or x.get("opened_at") or ""),reverse=True)[:limit]
 return jsonify(rows)

@app.post("/api/refresh")
@login_required
def api_refresh():
 try:
  fetch_snapshot(force=True)
  return jsonify({"success":True})
 except Exception as exc:
  return jsonify({"success":False,"error":str(exc)}),500

@app.get("/health")
def health():
 try:
  snap=fetch_snapshot()
  return jsonify({"ok":True,"source":snap.get("source"),"simulation_only":True})
 except Exception as exc:
  return jsonify({"ok":False,"error":str(exc)}),500

if __name__=="__main__":
 app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")))
