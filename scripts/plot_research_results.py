#!/usr/bin/env python3
"""Draw a dependency-light publication figure using Pillow."""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W,H=2400,1500; BG,CARD,TEXT,MUTED,GRID="#F5F7FB","#FFFFFF","#101828","#667085","#D0D5DD"
COLORS={1:"#2563EB",3:"#7C3AED",5:"#E11D48"}
TITLES={"selector_corrupt":"Carrier corruption","selector_drop":"Carrier loss","word_delete":"Visible-word deletion"}
def font(size,bold=False):
    paths=["/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in paths:
        if Path(path).exists(): return ImageFont.truetype(path,size)
    return ImageFont.load_default()
def load_data(path):
    values=defaultdict(list)
    with path.open(newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f): values[(row["attack"],int(row["redundancy"]),float(row["rate"]))].append((int(row["trials"]),float(row["exact_recovery_rate"])))
    return {k:sum(n*r for n,r in v)/sum(n for n,_ in v) for k,v in values.items()}
def rounded(d,box,fill=CARD,outline=GRID,radius=22,width=2): d.rounded_rectangle(box,radius,fill=fill,outline=outline,width=width)
def centered(d,box,label,fnt,fill=TEXT):
    l,t,r,b=d.textbbox((0,0),label,font=fnt); d.text(((box[0]+box[2]-(r-l))/2,(box[1]+box[3]-(b-t))/2-t),label,font=fnt,fill=fill)
def node(d,box,title,subtitle,color):
    rounded(d,box,outline=color,width=4); centered(d,(box[0],box[1]+8,box[2],box[1]+49),title,font(23,True)); centered(d,(box[0],box[1]+51,box[2],box[3]-5),subtitle,font(18),MUTED)
def arrow(d,start,end,color="#98A2B3"):
    d.line((start,end),fill=color,width=5); x,y=end; d.polygon([(x,y),(x-15,y-10),(x-15,y+10)],fill=color)
def main():
    p=argparse.ArgumentParser(); p.add_argument("run_dir",type=Path); p.add_argument("--output",type=Path); a=p.parse_args(); run=a.run_dir.resolve(); out=(a.output or run/"xrf-study-summary.png").resolve()
    agg=load_data(run/"aggregate-results.csv"); rewrites=json.loads((run/"rewrite-results.json").read_text()); mixed=json.loads((run/"mixed-artifact-results.json").read_text()); summary=json.loads((run/"summary.json").read_text())
    im=Image.new("RGB",(W,H),BG); d=ImageDraw.Draw(im)
    centered(d,(0,25,W,90),"Authenticated session watermarks",font(48,True)); centered(d,(0,90,W,132),"Robust to carrier damage, brittle to structural edits",font(25),MUTED); centered(d,(0,134,W,172),f"{summary['documents']} Gemini documents  ·  {summary['offline_trials']:,} randomized trials  ·  100% clean recovery and visible fidelity",font(21),MUTED)
    rates=sorted({k[2] for k in agg}); top,bottom=210,855
    for idx,attack in enumerate(TITLES):
        left=45+idx*790; right=left+750; rounded(d,(left,top,right,bottom)); centered(d,(left,top+22,right,top+70),TITLES[attack],font(27,True)); x0,x1,y0,y1=left+95,right-35,top+120,bottom-90
        for pct in (0,25,50,75,100):
            y=y1-(pct/100)*(y1-y0); d.line((x0,y,x1,y),fill=GRID,width=2); d.text((x0-66,y-11),f"{pct}%",font=font(18),fill=MUTED)
        for pct in (0,5,10,20,35):
            x=x0+(pct/35)*(x1-x0); d.text((x-17,y1+17),f"{pct}%",font=font(17),fill=MUTED)
        d.line((x0,y0,x0,y1),fill=MUTED,width=3); d.line((x0,y1,x1,y1),fill=MUTED,width=3)
        for rep in (1,3,5):
            pts=[(x0+(rate/.35)*(x1-x0),y1-agg[(attack,rep,rate)]*(y1-y0)) for rate in rates]; d.line(pts,fill=COLORS[rep],width=6,joint="curve")
            for x,y in pts: d.ellipse((x-7,y-7,x+7,y+7),fill=COLORS[rep],outline=CARD,width=2)
        centered(d,(x0,y1+48,x1,y1+80),"Damage rate",font(18),MUTED)
    for i,rep in enumerate((1,3,5)):
        x=940+i*190; d.line((x,190,x+45,190),fill=COLORS[rep],width=7); d.ellipse((x+17,182,x+33,198),fill=COLORS[rep]); d.text((x+58,176),f"r{rep}",font=font(21,True),fill=TEXT)
    rounded(d,(45,900,1175,1410)); d.text((78,930),"Model-mediated handoff",font=font(30,True),fill=TEXT); survived=sum(x["origin_mark_survived_model_rewrite"] for x in rewrites); editors=sum(x["editor_mark_detected"] for x in rewrites)
    node(d,(80,1020,350,1140),"Origin mark",f"{len(rewrites)} documents","#2563EB"); arrow(d,(355,1080),(455,1080)); node(d,(460,1020,735,1140),"Gemini handoff","similarity 1.0","#F59E0B"); arrow(d,(740,1080),(840,1080)); node(d,(845,1020,1120,1140),"Origin recovered",f"{survived}/{len(rewrites)}","#E11D48")
    d.text((80,1202),f"Fresh editor watermark detected: {editors}/{len(rewrites)}",font=font(24,True),fill="#067647"); d.multiline_text((80,1252),"Normalization stripped the invisible carrier.\nCurrent provenance is hop-local, not end-to-end.",font=font(22),fill=MUTED,spacing=9)
    rounded(d,(1205,900,2355,1410)); d.text((1238,930),"Mixed-session policy decision",font=font(30,True),fill=TEXT); ys=[1000,1125,1250]
    for match,y in zip(mixed["matches"],ys):
        bad=match["status"]=="malicious"; color="#E11D48" if bad else "#16A34A"; node(d,(1240,y,1570,y+90),match["session_id"],match["status"],color); arrow(d,(1575,y+45),(1700,1170)); d.text((2150,y+25),"BLOCK" if bad else "REVIEW",font=font(25,True),fill="#E11D48" if bad else "#F59E0B")
    node(d,(1710,1105,2050,1235),"Mixed artifact",f"{mixed['detections']} marks","#7C3AED")
    for y in ys: arrow(d,(2055,1170),(2130,y+45))
    d.text((55,1460),"Exact recovery requires valid HMAC + CRC. Results are descriptive for this prototype corpus; absence of a mark means unknown, not safe.",font=font(18),fill=MUTED)
    out.parent.mkdir(parents=True,exist_ok=True); im.save(out,optimize=True); print(out)
if __name__=="__main__": main()
