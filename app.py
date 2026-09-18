
import os, csv, re, time, smtplib, ssl, threading
from html import escape
from io import BytesIO
from email.message import EmailMessage
from functools import wraps

import requests
from requests.adapters import HTTPAdapter
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

BASE_DIR=os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR,".env"))

app=Flask(__name__)
app.secret_key=os.getenv("FLASK_SECRET_KEY","CHANGE-ME")

SIMULATION_BASE_URL=os.getenv("SIMULATION_BASE_URL","").rstrip("/")
SIMULATION_DASHBOARD_API_KEY=os.getenv("SIMULATION_DASHBOARD_API_KEY","").strip()
COUNTY_MAIN_FILENAME=os.getenv("COUNTY_MAIN_FILENAME","county_main.csv").strip()
AGENTS_LOGIN_FILENAME=os.getenv("AGENTS_LOGIN_FILENAME","agents_login.csv").strip()
CACHE_SECONDS=int(os.getenv("CACHE_SECONDS","3"))
SIMULATION_API_READ_TIMEOUT_SECONDS=max(30,int(os.getenv("SIMULATION_API_READ_TIMEOUT_SECONDS","100") or 100))

AUTH_USERNAME=os.getenv("AUTH_USERNAME","").strip()
AUTH_PASSWORD_HASH=os.getenv("AUTH_PASSWORD_HASH","").strip()
SMTP_HOST=os.getenv("SMTP_HOST","").strip()
SMTP_PORT=int(os.getenv("SMTP_PORT","587") or 587)
SMTP_USERNAME=os.getenv("SMTP_USERNAME","").strip()
SMTP_PASSWORD=os.getenv("SMTP_PASSWORD","")
SMTP_FROM_EMAIL=os.getenv("SMTP_FROM_EMAIL",SMTP_USERNAME).strip()
SMTP_FROM_NAME=os.getenv("SMTP_FROM_NAME","2027 Presidential Simulation Results").strip()
SMTP_USE_TLS=os.getenv("SMTP_USE_TLS","true").strip().lower() in {"1","true","yes","on"}
SMTP_USE_SSL=os.getenv("SMTP_USE_SSL","false").strip().lower() in {"1","true","yes","on"}

_cache={"snapshot_at":0.0,"snapshot":None,"hierarchy":None,"registered":None}
_snapshot_lock=threading.Lock()
http=requests.Session()
http.mount("http://",HTTPAdapter(pool_connections=4,pool_maxsize=8,max_retries=1))
http.mount("https://",HTTPAdapter(pool_connections=4,pool_maxsize=8,max_retries=1))

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

def geo_key(value):
 return tuple(norm(value.get(k,"")) for k in ("county","constituency","ward","poll_station","stream"))

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
 with _snapshot_lock:
  # Summary, chart and stream-detail requests arrive together. Recheck the
  # cache after taking the lock so only one of them contacts the voting app.
  now=time.time()
  if not force and _cache["snapshot"] is not None and now-_cache["snapshot_at"]<CACHE_SECONDS:
   return _cache["snapshot"]
  if not SIMULATION_BASE_URL or not SIMULATION_DASHBOARD_API_KEY:
   raise RuntimeError("Simulation dashboard connection is not configured.")
  try:
   r=http.get(
    f"{SIMULATION_BASE_URL}/api/dashboard/president",
    headers={"X-Dashboard-Key":SIMULATION_DASHBOARD_API_KEY,"Accept":"application/json"},
    timeout=(6,SIMULATION_API_READ_TIMEOUT_SECONDS)
   )
   if not r.ok:
    raise RuntimeError(f"Voting system API temporarily unavailable (HTTP {r.status_code}). Please retry shortly.")
   data=r.json()
   if not isinstance(data,dict) or "streams" not in data:
    raise RuntimeError("Simulation API returned an invalid presidential snapshot.")
  except requests.Timeout:
   if _cache["snapshot"] is not None:
    return _cache["snapshot"]
   raise RuntimeError(
    "The voting system is still synchronizing the Kobo membership register. "
    "Please wait about one minute and select Refresh Now."
   )
  except Exception:
   if _cache["snapshot"] is not None:
    return _cache["snapshot"]
   raise
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
 allowed={geo_key(x) for x in expected}
 return [x for x in snapshot.get("streams",[]) if geo_key(x) in allowed]

def membership_registered(snapshot,county="",constituency="",ward="",poll_station=""):
 rows=snapshot.get("registered_voter_breakdown")
 if not isinstance(rows,list):
  raise RuntimeError("Voting API has not supplied the Kobo membership-register breakdown.")
 filters={"county":county,"constituency":constituency,"ward":ward,"poll_station":poll_station}
 return sum(to_int(row.get("registered_voters")) for row in rows
            if all(not value or norm(row.get(field))==norm(value) for field,value in filters.items()))

def summary_payload(county="",constituency="",ward=""):
 snap=fetch_snapshot()
 expected=filtered_expected(county,constituency,ward)
 streams=filtered_snapshot_streams(snap,county,constituency,ward)
 expected_keys={geo_key(x) for x in expected}
 stream_by_key={geo_key(x):x for x in streams}

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
 registered=membership_registered(snap,county,constituency,ward)
 if not county and not constituency and not ward:
  upstream_registered=to_int((snap.get("totals") or {}).get("registered_voters"))
  if upstream_registered:
   registered=upstream_registered
 no_participation=max(0,registered-participants)
 skip_pct=round(skipped/registered*100,2) if registered else 0
 turnout_pct=round(participants/registered*100,2) if registered else 0

 station_expected={}
 for g in expected:
  station_key=tuple(norm(g.get(k,"")) for k in ("county","constituency","ward","poll_station"))
  station_expected.setdefault(station_key,set()).add(geo_key(g))
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

 # Candidate performance by county. Percentages use deliberate candidate votes cast
 # in that county as the denominator; skipped presidential categories are excluded.
 hp=load_hierarchy()
 geo_by_stream={geo_key(x):x for x in hp["expected"]}
 county_stats={}
 for row in streams:
  geo=geo_by_stream.get(geo_key(row),{})
  ckey=geo.get("county","")
  if not ckey: continue
  c=county_stats.setdefault(ckey,{"county":geo.get("county_label") or friendly(ckey),"total_votes_cast":0,"candidate_votes":{}})
  cv=row.get("candidate_votes") or {}
  for cid,n in cv.items():
   n=to_int(n); c["candidate_votes"][cid]=c["candidate_votes"].get(cid,0)+n; c["total_votes_cast"]+=n
 county_results=[]
 counties_25={cid:0 for cid in candidate_names}
 for c in sorted(county_stats.values(),key=lambda x:x["county"]):
  total=c["total_votes_cast"]
  vals=[]
  for cid in candidate_names:
   votes=c["candidate_votes"].get(cid,0)
   pct=round(votes/total*100,2) if total else 0
   if total and pct>=25: counties_25[cid]=counties_25.get(cid,0)+1
   vals.append({"candidate_id":cid,"candidate":candidate_names.get(cid,cid),"votes":votes,"percent":pct})
  vals.sort(key=lambda x:(-x["votes"],x["candidate"].lower()))
  county_results.append({"county":c["county"],"total_votes_cast":total,"candidates":vals})
 candidate_county_25=[{"candidate_id":cid,"candidate":candidate_names.get(cid,cid),"counties_25_plus":counties_25.get(cid,0)} for cid in candidate_names]
 candidate_county_25.sort(key=lambda x:(-x["counties_25_plus"],x["candidate"].lower()))

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
   "total_votes_not_cast":no_participation,
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
  "county_candidate_percentages":county_results,
  "candidate_counties_25_plus":candidate_county_25,
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

def valid_email(value):
 return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",str(value or "").strip()))

def results_table_style():
 return TableStyle([
  ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#F3F4F6")),
  ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
  ("FONTNAME",(0,1),(-1,-1),"Helvetica"),
  ("FONTSIZE",(0,0),(-1,-1),9),
  ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
  ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#CCCCCC")),
  ("BOTTOMPADDING",(0,0),(-1,-1),6),
  ("TOPPADDING",(0,0),(-1,-1),6),
 ])

def build_results_pdf(summary):
 buf=BytesIO()
 doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=16*mm,leftMargin=16*mm,topMargin=14*mm,bottomMargin=14*mm,title="Presidential Candidate Results - Training Simulation Only")
 styles=getSampleStyleSheet()
 title_style=ParagraphStyle("TitleCenter",parent=styles["Title"],alignment=TA_CENTER,fontSize=16,leading=20,spaceAfter=6)
 notice_style=ParagraphStyle("Notice",parent=styles["Normal"],alignment=TA_CENTER,fontSize=9,leading=12,textColor=colors.HexColor("#A14E00"),spaceAfter=10)
 meta_style=ParagraphStyle("Meta",parent=styles["Normal"],fontSize=9,leading=12,spaceAfter=10)
 f=summary.get("filters") or {}
 county=friendly(f.get("county")) or "National"
 constituency=friendly(f.get("constituency")) or "All Constituencies"
 ward=friendly(f.get("ward")) or "All Wards"
 totals=summary.get("totals") or {}
 reporting=summary.get("reporting") or {}
 story=[
  Paragraph("2027 Presidential Simulation Results",title_style),
  Paragraph("<b>TRAINING / SIMULATION ONLY — NON-BINDING</b>",notice_style),
  Paragraph(f"<b>County:</b> {escape(county)}<br/><b>Constituency:</b> {escape(constituency)}<br/><b>Ward:</b> {escape(ward)}",meta_style),
  Paragraph(
   f"<b>Total Votes Cast:</b> {to_int(totals.get('candidate_selections')):,} &nbsp;&nbsp; "
   f"<b>Total Votes Skipped:</b> {to_int(totals.get('skipped')):,} &nbsp;&nbsp; "
   f"<b>Participants:</b> {to_int(totals.get('participants')):,}<br/>"
   f"<b>Registered Voters:</b> {to_int(totals.get('registered_voters')):,} &nbsp;&nbsp; "
   f"<b>Turnout:</b> {totals.get('turnout_percent',0)}% &nbsp;&nbsp; "
   f"<b>Streams Closed:</b> {to_int(reporting.get('closed_streams')):,} / {to_int(reporting.get('expected_streams')):,}",meta_style),
 ]
 data=[["Rank","Candidate","Votes","Share"]]
 candidates=summary.get("candidates") or []
 if candidates:
  for i,row in enumerate(candidates,1):
   data.append([str(i),Paragraph(escape(str(row.get("candidate") or "")),styles["Normal"]),f"{to_int(row.get('votes')):,}",f"{row.get('share',0)}%"])
 else:
  data.append(["","No presidential candidate selections yet.","0","0%"])
 table=Table(data,colWidths=[18*mm,100*mm,28*mm,25*mm],repeatRows=1)
 table.setStyle(results_table_style())
 table.setStyle(TableStyle([("ALIGN",(0,0),(0,-1),"CENTER"),("ALIGN",(2,1),(-1,-1),"RIGHT")]))
 story.extend([table,Spacer(1,7*mm)])

 county25=summary.get("candidate_counties_25_plus") or []
 if county25:
  story.append(Paragraph("Counties With 25% or More of Votes Cast",styles["Heading2"]))
  stats=[["Candidate","Counties ≥25%"]]+[[Paragraph(escape(str(x.get("candidate") or "")),styles["Normal"]),str(to_int(x.get("counties_25_plus")))] for x in county25]
  stats_table=Table(stats,colWidths=[125*mm,45*mm],repeatRows=1)
  stats_table.setStyle(results_table_style())
  story.extend([stats_table,Spacer(1,7*mm)])
 story.append(Paragraph("This report is generated from a training/simulation dashboard and does not constitute an official election result.",styles["Italic"]))
 doc.build(story)
 return buf.getvalue()

def send_results_email(recipient,pdf_bytes,summary):
 if not SMTP_HOST or not SMTP_FROM_EMAIL:
  raise RuntimeError("Email service is not configured on this dashboard.")
 f=summary.get("filters") or {}
 county=friendly(f.get("county")) or "National"
 constituency=friendly(f.get("constituency")) or "All Constituencies"
 ward=friendly(f.get("ward")) or "All Wards"
 candidate_lines=[f"{i}. {row.get('candidate') or ''}: {to_int(row.get('votes')):,} votes ({row.get('share',0)}%)" for i,row in enumerate(summary.get("candidates") or [],1)]
 candidate_results="\n".join(candidate_lines) or "No presidential candidate selections yet."
 county25_lines=[f"{row.get('candidate') or ''}: {to_int(row.get('counties_25_plus'))} counties" for row in summary.get("candidate_counties_25_plus") or []]
 county25_results="\n".join(county25_lines) or "No county vote data yet."
 msg=EmailMessage()
 msg["Subject"]=f"Presidential Simulation Candidate Results — {county}"
 msg["From"]=f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>" if SMTP_FROM_NAME else SMTP_FROM_EMAIL
 msg["To"]=recipient
 msg.set_content(
  "Attached are the current 2027 Presidential Simulation Candidate Results.\n\n"
  "TRAINING / SIMULATION ONLY — NON-BINDING\n"
  f"County: {county}\nConstituency: {constituency}\nWard: {ward}\n\n"
  f"Candidate Results:\n{candidate_results}\n\n"
  f"Counties With 25% or More:\n{county25_results}\n\n"
  "This dashboard is for training and simulation only and does not constitute an official election result."
 )
 safe_scope=re.sub(r"[^A-Za-z0-9_-]+","_",county).strip("_") or "National"
 msg.add_attachment(pdf_bytes,maintype="application",subtype="pdf",filename=f"Presidential_Simulation_Results_{safe_scope}.pdf")
 if SMTP_USE_SSL:
  with smtplib.SMTP_SSL(SMTP_HOST,SMTP_PORT,timeout=30,context=ssl.create_default_context()) as server:
   if SMTP_USERNAME:server.login(SMTP_USERNAME,SMTP_PASSWORD)
   server.send_message(msg)
 else:
  with smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=30) as server:
   server.ehlo()
   if SMTP_USE_TLS:
    server.starttls(context=ssl.create_default_context());server.ehlo()
   if SMTP_USERNAME:server.login(SMTP_USERNAME,SMTP_PASSWORD)
   server.send_message(msg)

@app.post("/api/email-results")
@login_required
def api_email_results():
 try:
  payload=request.get_json(silent=True) or {}
  recipient=str(payload.get("recipient") or "").strip()
  if not valid_email(recipient):return jsonify({"error":"Enter a valid recipient email address."}),400
  summary=summary_payload(payload.get("county",""),payload.get("constituency",""),payload.get("ward",""))
  send_results_email(recipient,build_results_pdf(summary),summary)
  return jsonify({"ok":True,"message":f"Results PDF emailed to {recipient}."})
 except Exception as exc:
  app.logger.exception("Email results failed")
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
 live={geo_key(x):x for x in filtered_snapshot_streams(snap,county,constituency,ward)}
 reg=load_registered()
 rows=[]
 for g in expected:
  x=live.get(geo_key(g),{})
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
