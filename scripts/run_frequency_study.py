#!/usr/bin/env python3
"""Benchmark fragment length × corruption × frame frequency × repetition."""
from __future__ import annotations
import argparse, csv, html, json, random, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from watermark_lab import WatermarkConfig, detect_watermark, embed_distributed_watermark, session_tag
from watermark_lab.core import _byte_to_selector, _selector_to_byte, _carrier_ends
from scripts.run_fragment_study import build_prose_lines

KEY=b"frequency-study-public-test-key-20260906-000000000000"
SESSION="frequency-study-origin"

def corrupt(text: str, rate: float, seed: int) -> str:
    rng=random.Random(seed); out=[]
    for ch in text:
        value=_selector_to_byte(ch)
        if value is None: out.append(ch)
        elif rng.random() < rate: out.append(_byte_to_selector(value ^ (1 << rng.randrange(8))))
        else: out.append(ch)
    return "".join(out)

def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n"); w.writeheader(); w.writerows(rows)

def color(rate: float) -> str:
    stops=[(0.0,(239,68,68)),(.5,(250,204,21)),(.9,(34,197,94)),(1.0,(16,185,129))]
    for (a,c1),(b,c2) in zip(stops,stops[1:]):
        if rate <= b:
            t=(rate-a)/(b-a); rgb=tuple(round(x+(y-x)*t) for x,y in zip(c1,c2)); return "#%02x%02x%02x"%rgb
    return "#10b981"

def svg_figure(rows: list[dict], meta: dict) -> str:
    lookup={(r["redundancy"],r["interval_carriers"],r["corruption_rate"],r["fragment_lines"]):r["exact_recovery_rate"] for r in rows}
    reps=meta["redundancies"]; intervals=meta["intervals"]; rates=meta["corruption_rates"]; lengths=meta["fragment_lengths"]
    W,H=2500,2020; left,top=230,340; pw,ph=690,430; gx,gy=75,105; cw=(pw-110)/len(lengths); ch=(ph-112)/len(rates)
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       '<rect width="100%" height="100%" fill="#f8fafc"/>',
       '<style>text{font-family:Inter,Arial,sans-serif;fill:#14213d}.title{font-weight:750}.muted{fill:#64748b}.axis{font-size:16px;font-weight:650}.tick{font-size:15px}.cell{font-size:16px;font-weight:700}.panel{fill:#fff;stroke:#cbd5e1;stroke-width:1.5}</style>',
       '<text x="1200" y="65" text-anchor="middle" class="title" font-size="42">Distributed watermark recovery: four interacting dimensions</text>',
       f'<text x="1200" y="108" text-anchor="middle" class="muted" font-size="21">{meta["corpus_lines"]:,} input lines · {meta["trials_per_cell"]} random fragments per cell · exact authenticated session recovery</text>',
       '<text x="1200" y="155" text-anchor="middle" font-size="18">Columns: placement interval (smaller = more frequent) · Rows: symbol repetition · Cell axes: copied fragment size × carrier corruption</text>']
    # Color legend.
    lx,ly=875,205
    for i in range(101): s.append(f'<rect x="{lx+i*7}" y="{ly}" width="8" height="20" fill="{color(i/100)}"/>')
    s += [f'<text x="{lx-12}" y="{ly+16}" text-anchor="end" class="tick">0%</text>',f'<text x="{lx+350}" y="{ly-12}" text-anchor="middle" class="axis">Exact authenticated recovery probability</text>',f'<text x="{lx+720}" y="{ly+16}" class="tick">100%</text>']
    for ri,rep in enumerate(reps):
        y=top+ri*(ph+gy)
        s.append(f'<text x="62" y="{y+ph/2}" text-anchor="middle" transform="rotate(-90 62 {y+ph/2})" class="title" font-size="24">r{rep}: each frame byte repeated {rep}×</text>')
        for ci,interval in enumerate(intervals):
            x=left+ci*(pw+gx); s.append(f'<rect class="panel" x="{x}" y="{y}" width="{pw}" height="{ph}" rx="4"/>')
            if ri==0: s.append(f'<text x="{x+pw/2}" y="{y-24}" text-anchor="middle" class="title" font-size="24">Frame every {interval} eligible words</text>')
            s.append(f'<text x="{x+18}" y="{y+28}" class="muted" font-size="15">frequency ≈ 1/{interval} carriers</text>')
            hx=x+94; hy=y+50
            for yi,rate in enumerate(reversed(rates)):
                yy=hy+yi*ch
                s.append(f'<text x="{hx-12}" y="{yy+ch/2+5}" text-anchor="end" class="tick">{round(rate*100)}%</text>')
                for xi,length in enumerate(lengths):
                    xx=hx+xi*cw; val=lookup[(rep,interval,rate,length)]; fill=color(val); tc="#ffffff" if val<.24 or val>.78 else "#14213d"
                    s.append(f'<rect x="{xx}" y="{yy}" width="{cw}" height="{ch}" fill="{fill}" stroke="#ffffff" stroke-width="3"/>')
                    s.append(f'<text x="{xx+cw/2}" y="{yy+ch/2+6}" text-anchor="middle" class="cell" style="fill:{tc}">{val:.0%}</text>')
            for xi,length in enumerate(lengths): s.append(f'<text x="{hx+xi*cw+cw/2}" y="{hy+len(rates)*ch+25}" text-anchor="middle" class="tick">{length}</text>')
            if ci==0: s.append(f'<text x="{x+18}" y="{hy+len(rates)*ch/2}" text-anchor="middle" transform="rotate(-90 {x+18} {hy+len(rates)*ch/2})" class="axis">Carrier corruption rate</text>')
            s.append(f'<text x="{hx+len(lengths)*cw/2}" y="{y+ph-12}" text-anchor="middle" class="axis">Copied fragment length (lines)</text>')
    fy=1940
    s += [f'<line x1="160" y1="{fy-32}" x2="2240" y2="{fy-32}" stroke="#cbd5e1"/>',
          f'<text x="160" y="{fy}" class="title" font-size="20">How to read:</text>',
          f'<text x="300" y="{fy}" font-size="18">Move right for larger consumed inputs; move upward inside a panel for more corruption; compare columns for watermark frequency and rows for repetition.</text>',
          f'<text x="160" y="{fy+38}" class="muted" font-size="17">Each percentage is {meta["trials_per_cell"]} deterministic random contiguous fragments. HMAC + CRC must both validate. Synthetic corpus; descriptive, not a production guarantee.</text>',
          '</svg>']
    return "".join(s)

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--corpus-lines",type=int,default=1200); p.add_argument("--trials",type=int,default=20); p.add_argument("--output-root",default="frequency_studies"); a=p.parse_args()
    lengths=[10,25,50,100,200]; rates=[0,.05,.10,.20,.35]; intervals=[100,300,600]; reps=[1,3,5]
    corpus="\n".join(build_prose_lines(a.corpus_lines,20260906))+"\n"; rows=[]
    for rep in reps:
        config=WatermarkConfig(8,rep); expected=session_tag(KEY,SESSION,8).hex()
        for interval in intervals:
            marked=embed_distributed_watermark(corpus,SESSION,KEY,config,interval); lines=marked.splitlines()
            for rate in rates:
                for length in lengths:
                    hits=0
                    for trial in range(a.trials):
                        rng=random.Random(9_000_000+rep*100_000+interval*100+round(rate*100)*10+length+trial); start=rng.randrange(0,len(lines)-length+1); frag="\n".join(lines[start:start+length]); damaged=corrupt(frag,rate,rng.randrange(1<<30)); hits += detect_watermark(damaged,rep).tag_hex==expected
                    rows.append({"redundancy":rep,"interval_carriers":interval,"corruption_rate":rate,"fragment_lines":length,"trials":a.trials,"exact_recovery_rate":hits/a.trials})
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S"); root=Path(a.output_root)/f"frequency-study-{stamp}"; root.mkdir(parents=True)
    meta={"created_at":datetime.now(timezone.utc).isoformat(),"corpus_lines":a.corpus_lines,"eligible_carriers":len(_carrier_ends(corpus)),"trials_per_cell":a.trials,"cells":len(rows),"total_trials":len(rows)*a.trials,"fragment_lengths":lengths,"corruption_rates":rates,"intervals":intervals,"redundancies":reps}
    write_csv(root/"frequency-results.csv",rows); (root/"summary.json").write_text(json.dumps(meta,indent=2)+"\n"); (root/"frequency-study.svg").write_text(svg_figure(rows,meta));
    (root/"REPORT.md").write_text(f"# Watermark frequency study\n\nThis study crosses {len(lengths)} fragment lengths, {len(rates)} corruption rates, {len(intervals)} frame intervals, and {len(reps)} repetition levels: **{meta['total_trials']:,} trials** across {len(rows)} cells. Smaller intervals mean more frequent complete frames. See `frequency-study.svg` and `frequency-results.csv`.\n")
    print(root); return 0
if __name__=="__main__": raise SystemExit(main())
