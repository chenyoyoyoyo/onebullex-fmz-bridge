// SPDX-License-Identifier: MPL-2.0
'use strict';
const test=require('node:test'),a=require('node:assert/strict');
const {createAlligatorEngine:make,alligatorDecision:decide}=require('./engine');
const M=60000;
function bars(n){let seed=31,price=80000;const rand=()=>{seed=(seed*16807)%2147483647;return seed/2147483647;};return Array.from({length:n},(_,i)=>{const open=price;price+=(rand()-.5)*100;return {Time:i*M,Open:open,Close:price,High:Math.max(open,price)+rand()*10,Low:Math.min(open,price)-rand()*10};});}
// Independent batch oracle: direct Pine history-index formulas, with full arrays.
function reference(rows){
 const ma=n=>rows.map((r,i)=>i<n-1?null:0).reduce((out,_,i)=>{
  out.push(i<n-1?null:i===n-1?rows.slice(0,n).reduce((s,r)=>s+(r.High+r.Low)/2,0)/n:(out[i-1]*(n-1)+(rows[i].High+rows[i].Low)/2)/n);return out;
 },[]);
 const jaw=ma(13),teeth=ma(8),lips=ma(5),high=[],low=[],frames=[];
 const cross=(x,y,px,py,up)=>[x,y,px,py].every(v=>v!=null)&&(up?x>y&&px<=py:x<y&&px>=py);
 rows.forEach((b,i)=>{
  const h=i>=4&&[i-4,i-3,i-1,i].every(j=>rows[j].High<rows[i-2].High);
  const l=i>=4&&[i-4,i-3,i-1,i].every(j=>rows[j].Low>rows[i-2].Low);
  high[i]=h?rows[i-2].High:(high[i-1]??null);low[i]=l?rows[i-2].Low:(low[i-1]??null);
  const t=teeth[i-5]??null,p=rows[i-1],pt=teeth[i-6]??null;
  frames.push({jaw:jaw[i-8]??null,teeth:t,lips:lips[i-3]??null,high:high[i],low:low[i],highConfirmed:h,lowConfirmed:l,
   long:!!p&&cross(b.Close,high[i],p.Close,high[i-1],true)&&t!==null&&b.Close>t,
   short:!!p&&cross(b.Close,low[i],p.Close,low[i-1],false)&&t!==null&&b.Close<t,
   exitLong:!!p&&cross(b.Close,t,p.Close,pt,false),exitShort:!!p&&cross(b.Close,t,p.Close,pt,true)});
 });return frames;
}
test('700 bars match independent Pine-series oracle for all SMMA offsets, fractals and crossings',()=>{
 const rows=bars(700),ref=reference(rows),e=make();let longs=0,shorts=0;
 rows.forEach((b,i)=>{const f=e.push(b);for(const [k,v]of Object.entries(ref[i]))a.equal(f[k],v,`${i} ${k}`);longs+=f.long;shorts+=f.short;});a.ok(longs>0&&shorts>0);
});
test('fractals require two CLOSED bars to the right, strict comparisons reject tied extrema',()=>{
 const row=(i,h)=>({Time:i*M,Open:5,Close:5,Low:1,High:h});const e=make();[6,7,10,8].forEach((h,i)=>a.equal(e.push(row(i,h)).high,null));a.equal(e.push(row(4,7)).high,10);
 const t=make();[6,7,10,10,7].forEach((h,i)=>a.equal(t.push(row(i,h)).high,null));
});
test('checkpoint resume is bit-identical to uninterrupted indicators and rejects missing bars',()=>{
 const rows=bars(400),e=make();rows.slice(0,200).forEach(b=>e.push(b));const r=make(e.state());rows.slice(200).forEach(b=>a.deepEqual(r.push(b),e.push(b)));
 a.equal(e.push(rows.at(-1)),null);a.throws(()=>e.push({...rows.at(-1),Time:401*M}),/gap/);
});
test('decisions cover long/short entry, no pyramiding, both teeth exits and both reversals',()=>{
 a.deepEqual(decide({long:true},0),{direction:1,reason:'ENTRY_LONG'});a.deepEqual(decide({short:true},0),{direction:-1,reason:'ENTRY_SHORT'});
 a.equal(decide({long:true},1),null);a.equal(decide({short:true},-1),null);
 a.equal(decide({exitLong:true},1).direction,0);a.equal(decide({exitShort:true},-1).direction,0);
 a.equal(decide({long:true,exitShort:true},-1).reason,'REVERSE_LONG');a.equal(decide({short:true,exitLong:true},1).reason,'REVERSE_SHORT');
 a.throws(()=>decide({long:true,short:true},0),/Conflicting/);
});
test('invalid OHLC/period and nonnumeric data fail closed',()=>{
 for(const b of [{Time:1,Open:5,High:6,Low:4,Close:5},{Time:0,Open:5,High:4,Low:3,Close:5},{Time:0,Open:5,High:6,Low:4,Close:'5'}])a.throws(()=>make().push(b),/Invalid/);
});
