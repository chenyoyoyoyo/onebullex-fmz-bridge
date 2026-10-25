// SPDX-License-Identifier: MPL-2.0
/* Alligator + Fractal port of user-provided Pine v5, MPL-2.0.
 * Closed 1-minute candles only. SMMA state is incremental and restart-persistent.
 */
function createAlligatorEngine(saved) {
    'use strict';
    var s=saved ? JSON.parse(JSON.stringify(saved)) : {version:1,lastTime:null,bars:[],high:null,low:null,frame:null,
        ma:[{n:13,seed:[],value:null,history:[]},{n:8,seed:[],value:null,history:[]},{n:5,seed:[],value:null,history:[]}]};
    if(s.version!==1)throw Error('Indicator version mismatch');
    function cross(a,b,pa,pb,up) {
        return [a,b,pa,pb].every(function(v){return typeof v==='number' && Number.isFinite(v);}) &&
            (up ? a>b && pa<=pb : a<b && pa>=pb);
    }
    function push(b) {
        ['Time','Open','High','Low','Close'].forEach(function(k){if(typeof b[k]!=='number'||!Number.isFinite(b[k]))throw Error('Invalid candle '+k);});
        if(b.Time%60000 || b.Low<=0 || b.High<Math.max(b.Low,b.Open,b.Close) || b.Low>Math.min(b.Open,b.Close))throw Error('Invalid 1-minute candle');
        if(s.lastTime!==null && b.Time<=s.lastTime)return null;
        if(s.lastTime!==null && b.Time!==s.lastTime+60000)throw Error('Candle gap');
        var prev=s.frame,hl2=(b.High+b.Low)/2;
        s.ma.forEach(function(m){
            if(m.value===null){m.seed.push(hl2);if(m.seed.length===m.n){m.value=m.seed.reduce(function(a,v){return a+v;},0)/m.n;m.seed=[];}}
            else m.value=(m.value*(m.n-1)+hl2)/m.n;
            m.history.push(m.value);if(m.history.length>9)m.history.shift();
        });
        function shifted(i,offset){var arr=s.ma[i].history;return arr.length>offset?arr[arr.length-1-offset]:null;}
        s.bars.push({Time:b.Time,High:b.High,Low:b.Low});if(s.bars.length>5)s.bars.shift();
        var hi=false,lo=false,candidate=null;
        if(s.bars.length===5){
            candidate=s.bars[2];
            hi=s.bars.every(function(r,i){return i===2||r.High<candidate.High;});
            lo=s.bars.every(function(r,i){return i===2||r.Low>candidate.Low;});
            if(hi)s.high=candidate.High;if(lo)s.low=candidate.Low;
        }
        var f={time:b.Time,close:b.Close,jaw:shifted(0,8),teeth:shifted(1,5),lips:shifted(2,3),
            high:s.high,low:s.low,highConfirmed:hi,lowConfirmed:lo,fractalTime:candidate?candidate.Time:null};
        f.long=!!prev && cross(f.close,f.high,prev.close,prev.high,true) && f.teeth!==null && f.close>f.teeth;
        f.short=!!prev && cross(f.close,f.low,prev.close,prev.low,false) && f.teeth!==null && f.close<f.teeth;
        f.exitLong=!!prev && cross(f.close,f.teeth,prev.close,prev.teeth,false);
        f.exitShort=!!prev && cross(f.close,f.teeth,prev.close,prev.teeth,true);
        s.lastTime=b.Time;s.frame=f;return JSON.parse(JSON.stringify(f));
    }
    return {push:push,state:function(){return JSON.parse(JSON.stringify(s));}};
}
function alligatorDecision(frame,net) {
    // Original default pyramiding=0. Opposite entries take precedence over closing the old side.
    if(frame.long && frame.short)throw Error('Conflicting entry signals; manual review');
    if(frame.long && net<=0)return {direction:1,reason:net<0?'REVERSE_LONG':'ENTRY_LONG'};
    if(frame.short && net>=0)return {direction:-1,reason:net>0?'REVERSE_SHORT':'ENTRY_SHORT'};
    if(net>0 && frame.exitLong)return {direction:0,reason:'EXIT_LONG_TEETH'};
    if(net<0 && frame.exitShort)return {direction:0,reason:'EXIT_SHORT_TEETH'};
    return null;
}
if(typeof module!=='undefined' && module.exports)module.exports={createAlligatorEngine:createAlligatorEngine,alligatorDecision:alligatorDecision};
