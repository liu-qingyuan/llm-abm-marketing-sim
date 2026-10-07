#!/usr/bin/env python3
"""Exact SVG plots from checked CSV data, using only stdlib; no synthetic values."""
import argparse,csv,html,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
COLORS={'openai-codex/gpt-5.6-sol':'#1e293b','kimi-k3':'#b45309','gemini-3.1-pro':'#0f766e','deepseek-flash':'#7c3aed'}
def main(partial):
 folder=ROOT/('progress-report' if partial else 'formal-report');e=json.loads((folder/'evidence.json').read_text());rows=list(csv.DictReader((folder/'curves.csv').open()));assert e['conditions']==16 or partial
 for message in ['message_1','message_2','message_3']:
  body=['<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="420" viewBox="0 0 1440 420">','<rect width="1440" height="420" fill="white"/>',f'<text x="45" y="30" font-family="sans-serif" font-size="20">Ten-topic merged historical network · {html.escape(message)} · {e["conditions"]}/16 conditions accepted</text>']
  for prompt in range(4):
   left=52+prompt*352;top=70;width=300;height=230
   body.append(f'<text x="{left}" y="55" font-family="sans-serif" font-size="16">P{prompt}</text>')
   for y in [0,150,300,450,600]:
    screen=top+height-height*y/600;body.append(f'<line x1="{left}" x2="{left+width}" y1="{screen}" y2="{screen}" stroke="#e2e8f0"/><text x="{left-8}" y="{screen+4}" text-anchor="end" font-size="11" font-family="sans-serif">{y}</text>')
   for batch in [0,10,20,29]:body.append(f'<text x="{left+width*batch/29}" y="{top+height+20}" text-anchor="middle" font-size="11" font-family="sans-serif">{batch}</text>')
   data=[r for r in rows if r['template']==f'P{prompt}' and r['message']==message]
   for model,color in COLORS.items():
    points=sorted((int(r['batch']),int(r['realized_positive'])) for r in data if r['model_id']==model)
    if not points:continue
    assert len(points)==30 and [x for x,y in points]==list(range(30)) and all(0<=y<=600 for x,y in points)
    encoded=' '.join(f'{left+width*x/29:.3f},{top+height-height*y/600:.3f}' for x,y in points);body.append(f'<polyline points="{encoded}" fill="none" stroke="{color}" stroke-width="2.5"/>')
   if not data:body.append(f'<text x="{left+width/2}" y="{top+height/2}" text-anchor="middle" font-family="sans-serif" fill="#64748b">Pending formal completion</text>')
  labels={'openai-codex/gpt-5.6-sol':'GPT-5.6 Sol','kimi-k3':'Kimi','gemini-3.1-pro':'Gemini 3.1 Pro','deepseek-flash':'DeepSeek V4.1 Flash'}
  for i,(model,color) in enumerate(COLORS.items()):body.append(f'<text x="{80+350*i}" y="355" font-family="sans-serif" font-size="14" fill="{color}">{labels[model]}</text>')
  body.append('<text x="50" y="387" font-family="sans-serif" font-size="12" fill="#475569">Y: cumulative realized interactions (600 exposures per message). X: batch. One fixed behavior seed 20260823; adaptive paths are descriptive.</text></svg>');(folder/f'{message}-curves.svg').write_text('\n'.join(body))
 print('PLOTS messages=3 source=checked_actual_curves provider_calls=0')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--partial',action='store_true');main(p.parse_args().partial)
