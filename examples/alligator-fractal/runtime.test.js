// SPDX-License-Identifier: MPL-2.0
'use strict';
const test=require('node:test'),a=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {createAlligatorRuntime:make}=require('./runtime');
const M=60000,T=Date.UTC(2026,9,25);
function fixture(opt={}){
 let clock=T+100*M+1000,price=80000,net=0,avg=0,wallet=63,journal=null,saved=null,order=null,seq=0;
 const rows=Array.from({length:100},(_,i)=>({Time:T+i*M,Open:80000,Close:80000,High:80001,Low:79999}));
 rows[95].High=80020;rows[96].Low=79980;
 const sends=[],logs=[],events=[];let failReads=0;
 const positions=()=>net?[{symbol:'btc_usdt',positionSize:String(Math.abs(net)),positionSide:net>0?'LONG':'SHORT',entryPrice:String(avg),contractSize:'0.0001'}]:[];
 const ex={GetCurrency:()=> 'BTC_USDT',GetLabel:()=> 'OneBullEx-Spartans',GetOrders:()=>opt.openOrders||[],
  GetRecords:p=>{a.equal(p,60);return rows;},GetTicker:()=>({Last:price,Time:clock-(opt.stale?30000:0)}),
  IO:(api,verb,path)=>{a.equal(api,'api');a.equal(verb,'GET');
   if(path.endsWith('symbol/detail'))return {data:{symbol:'btc_usdt',contractSize:'0.0001',quantityPrecision:0,minQty:'1',minStepPrice:'.1'}};
   if(path.endsWith('position/list')){if(failReads-->0)throw Error('MOCK_TIMEOUT');return {data:positions()};}
   if(path.endsWith('balance/list'))return {data:[{coin:'USDT',walletBalance:String(wallet)}]};
   if(path.endsWith('symbol-mark-price'))return {data:{p:String(price)}};
   throw Error('Unexpected '+path);
  },GetOrder:id=>{a.equal(id,order.id);events.push('fill-query');
   if(opt.lookupFailure)return null;
   if(opt.partial)return {Amount:order.q,DealAmount:0,Status:2,AvgPrice:0};
   if(!opt.noSync){net=order.target;avg=net?order.price:0;}
   return {Amount:order.q,DealAmount:order.q,Status:1,AvgPrice:opt.noAvg?0:order.price};
  }
 };
 function send(side,p,q){a.equal(p,-1);a.ok(journal&&saved.intent,'persist both journals BEFORE sending');a.equal(journal.state,'sending');
  sends.push({side,q});events.push('send:'+side);order={id:'order-'+(++seq),q,target:net+(side==='Buy'?q:-q),price:price+(opt.slippage||0)};
  if(opt.unknown){net=order.target;avg=order.price;return null;}return order.id;
 }
 ex.Buy=(p,q)=>send('Buy',p,q);ex.Sell=(p,q)=>send('Sell',p,q);
 const env={exchange:ex,now:()=>clock,sleep:ms=>{clock+=ms;},loadState:()=>saved,saveState:s=>{saved=structuredClone(s);},loadJournal:()=>journal,saveJournal:j=>{journal=j;},log:(...x)=>logs.push(x),status:()=>{}};
 const config={live:!!opt.live,maxRoundTrips:opt.rounds??1,...opt.config};let rt=make(env,config);
 const f={ex,env,config,sends,logs,events,rows,step:()=>rt.step(),saved:()=>structuredClone(saved),journal:()=>journal,net:()=>net,
  now:()=>clock,setPrice:p=>{price=p;},advance:ms=>{clock+=ms;},setWallet:v=>{wallet=v;},setNet:v=>{net=v;avg=price;},failReads:n=>{failReads=n;},
  mutate:fn=>fn(saved),restart:()=>{rt=make(env,config);return rt;},
  bar:(close,extra={})=>{const time=rows.at(-1).Time+M;rows.push({Time:time,Open:close,Close:close,High:close+1,Low:close-1,...extra});price=close;
   // Polls while the candle forms, exercising exclusion of the live candle.
   while(clock<time+M+1000){clock=Math.min(clock+10000,time+M+1000);rt.step();}return rt.state();}
 };return f;
}
test('default PAPER warms up immediately, excludes forming candles, then long and teeth-exit round trip with zero orders',()=>{
 const f=fixture();f.step();a.equal(f.saved().net,0);a.ok(f.logs.some(x=>x[0]==='READY_NO_REPLAY'));
 f.bar(80030);a.equal(f.saved().net,1);f.bar(79995);a.equal(f.saved().net,0);a.equal(f.saved().closedTrades,1);a.equal(f.saved().complete,true);a.deepEqual(f.sends,[]);
 f.restart();f.bar(79970);a.equal(f.saved().net,0);
});
test('LIVE long entry and entire exit use confirmed fill price and durable journals',()=>{
 const f=fixture({live:true,slippage:.2});f.step();f.bar(80030);a.equal(f.net(),1);a.equal(f.saved().avg,80030.2);
 f.bar(79995);a.equal(f.net(),0);a.equal(f.saved().complete,true);a.deepEqual(f.sends,[{side:'Buy',q:1},{side:'Sell',q:1}]);a.equal(f.saved().intent,null);a.equal(f.journal(),null);
});
test('short entry and teeth exit use Sell then Buy',()=>{
 const f=fixture({live:true});f.step();f.bar(79970);a.equal(f.net(),-1);f.bar(80005);a.equal(f.net(),0);a.deepEqual(f.sends,[{side:'Sell',q:1},{side:'Buy',q:1}]);
});
test('continuous mode reverse closes and confirms flat before opening opposite; both directions',()=>{
 const f=fixture({live:true,rounds:0});f.step();f.bar(80030);f.bar(79970);a.equal(f.net(),-1);f.bar(80040);a.equal(f.net(),1);
 a.deepEqual(f.sends.map(x=>x.side),['Buy','Sell','Sell','Buy','Buy']);a.equal(f.saved().closedTrades,2);
 a.deepEqual(f.events.slice(0,6),['send:Buy','fill-query','send:Sell','fill-query','send:Sell','fill-query']);
});
test('one-round validation stops flat before reversal reopening',()=>{
 const f=fixture({live:true});f.step();f.bar(80030);f.bar(79970);a.equal(f.net(),0);a.equal(f.saved().complete,true);a.equal(f.sends.length,2);
});
test('original 10% of actual wallet respects integer contracts: below one is skipped, not rounded up',()=>{
 const f=fixture({live:true,config:{sizeMode:0}});f.step();f.bar(80030);a.equal(f.saved().lastBlocked.reason,'BELOW_ONE_CONTRACT');a.equal(f.sends.length,0);
 const g=fixture({live:true,config:{sizeMode:0}});g.setWallet(100);g.step();g.bar(80030);a.equal(g.net(),1);
});
test('percentage size above approved cap is blocked without clipping or splitting',()=>{
 const f=fixture({live:true,config:{sizeMode:0}});f.setWallet(1000);f.step();f.bar(80030);a.equal(f.saved().lastBlocked.reason,'ABOVE_APPROVED_CAP');a.equal(f.sends.length,0);
});
test('blocked reverse size still executes independent teeth exit and remains flat',()=>{
 const f=fixture({live:true,rounds:0,config:{sizeMode:0}});f.setWallet(100);f.step();f.bar(80030);a.equal(f.net(),1);
 f.setWallet(30);f.bar(79970);a.equal(f.net(),0);a.equal(f.sends.length,2);a.equal(f.saved().lastBlocked.reason,'BELOW_ONE_CONTRACT');
});
test('finite read retries recover transient failure and stop after three failures without an order',()=>{
 const f=fixture({live:true});f.failReads(2);f.step();a.equal(f.logs.filter(x=>x[0]==='READ_RETRY').length,2);
 f.failReads(3);a.throws(()=>f.step(),/Read failed/);a.equal(f.sends.length,0);
});
for(const [flag,pattern] of [['unknown',/Unknown submission/],['lookupFailure',/Fill not confirmed/],['partial',/partially/],['noSync',/not synchronized/],['noAvg',/actual fill/]])test(flag+' retains intent and journal; restart cannot duplicate order',()=>{
 const f=fixture({live:true,[flag]:true});f.step();a.throws(()=>f.bar(80030),pattern);a.equal(f.sends.length,1);a.ok(f.saved().intent);a.ok(f.journal());a.throws(()=>f.restart(),/Unresolved/);a.equal(f.sends.length,1);
});
test('external position change and stale ticker block orders',()=>{
 const f=fixture({live:true});f.step();f.setNet(1);a.throws(()=>f.step(),/differs/);a.equal(f.sends.length,0);
 const g=fixture({live:true,stale:true});g.step();a.throws(()=>g.bar(80030),/Stale ticker/);a.equal(g.sends.length,0);
});
test('same closed candle may be polled throughout minute without duplicate order or false staleness',()=>{
 const f=fixture({live:true});f.step();f.advance(40000);f.step();a.equal(f.sends.length,0);f.bar(80030);f.step();f.step();a.equal(f.sends.length,1);
});
test('flat startup/restart never replays historical entry signals',()=>{
 const f=fixture({live:true});f.rows.at(-1).Close=80030;f.rows.at(-1).High=80031;f.step();a.equal(f.sends.length,0);f.restart();f.step();a.equal(f.sends.length,0);
});
test('held monitoring outage and interrupted intent block restart; flat missed bar safely reseeds',()=>{
 const f=fixture({live:true});f.step();f.bar(80030);f.advance(61000);a.throws(()=>f.restart(),/monitoring gap/);
 const g=fixture();g.step();g.mutate(s=>s.intent={id:1});a.throws(()=>g.restart(),/Unresolved/);
 const h=fixture({live:true});h.step();h.rows.push({...h.rows.at(-1),Time:T+100*M},{...h.rows.at(-1),Time:T+101*M});h.advance(2*M);h.step();a.equal(h.sends.length,0);a.equal(h.logs.filter(x=>x[0]==='READY_NO_REPLAY').length,2);
});
test('late signal entry is skipped; saved state has no ambiguous order intent',()=>{
 const f=fixture({live:true});f.step();f.rows.push({Time:T+100*M,Open:80030,Close:80030,High:80031,Low:80029});f.advance(M+30000);f.step();a.equal(f.saved().lastBlocked.reason,'STALE_SIGNAL');a.equal(f.saved().intent,null);a.equal(f.sends.length,0);
});
test('unordered or duplicate candle timestamps fail rather than compute misleading signals',()=>{
 const f=fixture();f.rows.push({...f.rows.at(-1)});a.throws(()=>f.step(),/order\/time/);
});
test('standalone bundle default main is PAPER and uses supported bridge APIs only',()=>{
 const src=fs.readFileSync(__dirname+'/Alligator-Fractal-OneBullEx.js','utf8'),f=fixture(),storage={};
 const context={exchange:f.ex,exchanges:[f.ex],Date:{now:f.now},Log:()=>{},LogStatus:()=>{},Sleep:()=>{throw Error('END_TEST_LOOP');},Chart:()=>({add:()=>{}}),_G:function(k,v){if(arguments.length>1)storage[k]=v;return storage[k];}};
 vm.createContext(context);vm.runInContext(src,context);a.throws(()=>context.main(),/END_TEST_LOOP/);a.equal(f.sends.length,0);a.ok(Object.keys(storage).some(k=>k.endsWith(':PAPER')));
 a.doesNotMatch(src,/\.(?:SetContractType|SetDirection|SetMarginLevel|GetPositions|CreateOrder)\s*\(/);a.doesNotMatch(src,/\brequire\s*\(/);
});
test('public account label is configurable and exact-match; mismatch never sends',()=>{
 const src=fs.readFileSync(__dirname+'/Alligator-Fractal-OneBullEx.js','utf8'),f=fixture();
 f.ex.GetLabel=()=> 'My-Spartans-Account';
 const context={exchange:f.ex,exchanges:[f.ex],Date:{now:f.now},Log:()=>{},LogStatus:()=>{},Sleep:()=>{throw Error('END_TEST_LOOP');},_G:()=>null};
 vm.createContext(context);vm.runInContext(src,context);
 a.throws(()=>context.main(),/configured Spartans account/);
 context.AF_ACCOUNT_LABEL='My-Spartans-Account';
 a.throws(()=>context.main(),/END_TEST_LOOP/);a.equal(f.sends.length,0);
});
test('approved larger fixed size is supported without a hardcoded one-contract ceiling',()=>{
 const f=fixture({live:true,config:{fixedContracts:3,cap:3}});f.step();f.bar(80030);a.equal(f.net(),3);f.bar(79995);
 a.equal(f.net(),0);a.deepEqual(f.sends,[{side:'Buy',q:3},{side:'Sell',q:3}]);
});
