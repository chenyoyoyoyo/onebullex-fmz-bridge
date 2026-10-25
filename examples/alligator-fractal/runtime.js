// SPDX-License-Identifier: MPL-2.0
/* Alligator runtime. No real orders in PAPER. Closed-bar crossings are market orders,
 * not exchange-native stops. Finite read retries never retry Buy/Sell submissions.
 */
function createAlligatorRuntime(env,options) {
    'use strict';
    var c=Object.assign({live:false,sizeMode:1,fixedContracts:1,equityPct:10,cap:1,maxRoundTrips:1,showLines:true},options||{});
    if(typeof c.live!=='boolean'||[0,1].indexOf(c.sizeMode)<0||typeof c.showLines!=='boolean')throw Error('Invalid mode');
    ['fixedContracts','cap','maxRoundTrips'].forEach(function(k){if(!Number.isSafeInteger(c[k])||c[k]<(k==='maxRoundTrips'?0:1))throw Error('Invalid '+k);});
    if(!Number.isFinite(c.equityPct)||c.equityPct<=0||c.equityPct>100)throw Error('Invalid equity percent');
    if(c.fixedContracts>c.cap)throw Error('Fixed size exceeds approved bridge cap');
    var ex=env.exchange,M=60000,unit=.0001;
    if(!ex||ex.GetCurrency()!=='BTC_USDT')throw Error('Attach BTC_USDT');
    function num(v,k){if(v===null||v===undefined||v===''||typeof v==='boolean'||!Number.isFinite(Number(v)))throw Error('Invalid '+k);return Number(v);}
    function read(fn,label){var last;for(var i=0;i<3;i++){try{var r=fn();if(r===null||r===undefined||r===false)throw Error('Empty read');return r;}catch(e){last=e;if(i<2){env.log('READ_RETRY',label,i+1);env.sleep(1000);}}}throw Error('Read failed: '+label+' '+String(last));}
    function data(path,q){return read(function(){var r=ex.IO('api','GET',path,q||'');if(typeof r==='string')r=JSON.parse(r);if(!r||r.data===null||r.data===undefined)throw Error('Missing data');return r.data;},path);}
    var makeExecution=typeof createSpartansExecution!=='undefined'?createSpartansExecution:require('./execution').createSpartansExecution;
    var makeEngine=typeof createAlligatorEngine!=='undefined'?createAlligatorEngine:require('./engine').createAlligatorEngine;
    var decide=typeof alligatorDecision!=='undefined'?alligatorDecision:require('./engine').alligatorDecision;
    var execution=makeExecution({exchange:ex,now:env.now,sleep:env.sleep,load:env.loadJournal,save:env.saveJournal,log:env.log},{liveEnabled:c.live,maxOrderContracts:c.cap});
    var spec=read(function(){return execution.spec();},'contract specification');
    if(spec.contractSize!==unit)throw Error('Unverified contract size');
    var signature=JSON.stringify({version:1,config:c}),stored=env.loadState();
    if(env.loadJournal() || stored && stored.intent)throw Error('Unresolved order journal/intent: do not resend');
    if(stored && stored.signature!==signature){if(stored.net)throw Error('Cannot change configuration with position');stored=null;}
    var s=stored||{signature:signature,indicators:null,net:0,avg:0,intent:null,heartbeat:null,paperWallet:null,
        entryFee:0,estimatedPnL:0,closedTrades:0,complete:false,sequence:0,lastSignal:null,lastBlocked:null};
    if(s.net && s.heartbeat!==null && env.now()-s.heartbeat>60000)throw Error('Held position monitoring gap; manual reconciliation');
    var engine=makeEngine(s.indicators);
    function save(){s.indicators=engine.state();s.heartbeat=env.now();env.saveState(JSON.parse(JSON.stringify(s)));}
    function account(){
        var ps=data('/v2/position/list');if(!Array.isArray(ps))throw Error('Invalid position response');
        var active=ps.filter(function(p){var q=num(p.positionSize,'position size');if(q<0)throw Error('Negative position size');return q>0;});
        if(active.length>1||active.some(function(p){return p.symbol!=='btc_usdt';}))throw Error('Unexpected account exposure');
        var p=active[0],net=0,avg=0;
        if(p){if(['LONG','SHORT'].indexOf(p.positionSide)<0)throw Error('Invalid position side');net=num(p.positionSize,'position size')*(p.positionSide==='LONG'?1:-1);avg=num(p.entryPrice,'entry price');if(!Number.isSafeInteger(net)||avg<=0||num(p.contractSize,'contractSize')!==unit)throw Error('Invalid position');}
        var orders=read(function(){return ex.GetOrders();},'open orders');if(!Array.isArray(orders)||orders.length)throw Error('Unexpected open orders');
        var expected=c.live?s.net:0;if(net!==expected)throw Error('Account position differs from saved strategy');
        if(c.live&&net&&Math.abs(avg-s.avg)>spec.priceStep+1e-8)throw Error('Position average changed outside strategy');
        return {net:net,avg:avg};
    }
    function wallet(){var bs=data('/v2/balance/list');if(!Array.isArray(bs))throw Error('Invalid balance response');var b=bs.filter(function(x){return String(x.coin).toUpperCase()==='USDT';});if(b.length!==1)throw Error('Missing USDT wallet');return num(b[0].walletBalance,'wallet');}
    function ticker(){var t=read(function(){return ex.GetTicker();},'ticker');t={Last:num(t.Last,'Last'),Time:num(t.Time,'Time')};if(t.Last<=0||Math.abs(env.now()-t.Time)>15000)throw Error('Stale ticker');return t;}
    function records(){var rows=read(function(){return ex.GetRecords(60);},'1-minute records');if(!Array.isArray(rows))throw Error('Missing candles');var now=env.now();rows.forEach(function(b,i){if(typeof b.Time!=='number'||!Number.isFinite(b.Time)||b.Time%M||i&&b.Time<=rows[i-1].Time)throw Error('Invalid candle order/time');});var closed=rows.filter(function(b){return b.Time+M<=now;});if(closed.length<100)throw Error('Need 100 closed 1-minute candles');if(now-(closed[closed.length-1].Time+M)>75000)throw Error('Latest closed candle stale');return closed;}
    function seed(rows){engine=makeEngine();rows.forEach(function(b){engine.push(b);});save();env.log('READY_NO_REPLAY',rows.length,engine.state().lastTime,'Next newly closed minute can trade; no daily warm-up');}
    account();if(s.paperWallet===null)s.paperWallet=wallet();
    function size(t){if(c.sizeMode===1)return c.fixedContracts;var eq;if(c.live){var mark=num(data('/v2/public/q/symbol-mark-price','symbol=btc_usdt').p,'mark price');if(mark<=0)throw Error('Invalid mark');eq=wallet()+(mark-s.avg)*s.net*unit;}else eq=s.paperWallet+(t.Last-s.avg)*s.net*unit;return Math.max(0,Math.floor(eq*c.equityPct/100/(t.Last*unit)));}
    function leg(target,reason){
        account();var t=ticker(),from=s.net;
        // Entry is allowed only briefly after the signal candle closed; exits still reduce risk.
        if(target!==0 && (env.now()-s.intent.signalTime-M>20000 || env.now()-s.intent.signalTime-M<0))throw Error('Signal expired before entry; reconcile intent');
        var q=Math.abs(target-from);if(q<1||q>c.cap)throw Error('Quantity exceeds approved cap');
        s.intent.phase=target===0?'CLOSING':'OPENING';s.intent.target=target;save();
        var price=t.Last;
        if(c.live){var done=execution.moveTo(target);if(done.dryRun||done.net!==target||done.fills.length!==1)throw Error('Unexpected execution result');price=done.fills[0].price;}
        var fee=q*unit*price*.0006,pnl=null;
        if(target===0){var gross=(price-s.avg)*from*unit;pnl=gross-s.entryFee-fee;s.estimatedPnL+=pnl;if(!c.live)s.paperWallet+=gross-fee;s.closedTrades++;s.avg=0;s.entryFee=0;}
        else {s.avg=price;s.entryFee=fee;if(!c.live)s.paperWallet-=fee;}
        s.net=target;save();account();
        env.log(c.live?'LIVE_CONFIRMED':'PAPER_FILL',{reason:reason,from:from,target:target,price:price,contracts:q,estimatedNetPnL:pnl});
    }
    function step(){
        if(s.complete){account();env.status(JSON.stringify({mode:c.live?'LIVE':'PAPER_NO_ORDERS',complete:true,net:s.net,closedTrades:s.closedTrades,estimatedPnL:s.estimatedPnL}));return {complete:true};}
        if(s.net&&s.heartbeat!==null&&env.now()-s.heartbeat>60000)throw Error('Monitoring gap with held position');
        account();var rows=records(),last=engine.state().lastTime;
        if(last===null){seed(rows);last=engine.state().lastTime;}
        var fresh=rows.filter(function(b){return b.Time>last;});
        if(fresh.length>1 || fresh.length===1&&fresh[0].Time-last!==M){if(s.net)throw Error('Missed candles with position');seed(rows);fresh=[];}
        if(fresh.length){
            var f=engine.push(fresh[0]),decision=decide(f,s.net);
            if(decision){
                s.lastSignal={time:f.time,reason:decision.reason,close:f.close,teeth:f.teeth,high:f.high,low:f.low};
                env.log('SIGNAL',s.lastSignal);
                var t=ticker(),qty=decision.direction?size(t):0;
                var late=env.now()-f.time-M>20000;
                var blocked=decision.direction && (qty<1||qty>c.cap||late);
                if(blocked){
                    s.lastBlocked={at:env.now(),contracts:qty,reason:late?'STALE_SIGNAL':qty<1?'BELOW_ONE_CONTRACT':'ABOVE_APPROVED_CAP'};
                    env.log('BLOCKED',s.lastBlocked); // Never round up or silently clip percentage sizing.
                    // A blocked reverse entry must not suppress the source's separate exit.
                    decision=s.net>0&&f.exitLong||s.net<0&&f.exitShort?{direction:0,reason:'EXIT_TEETH_ENTRY_BLOCKED'}:null;
                }
                if(decision){
                    s.intent={id:++s.sequence,signalTime:f.time,reason:decision.reason,desired:decision.direction*qty,phase:'PREPARED'};save();
                    if(s.net && (decision.direction===0 || Math.sign(s.net)!==decision.direction))leg(0,decision.reason);
                    if(c.maxRoundTrips>0 && s.closedTrades>=c.maxRoundTrips){s.complete=true;env.log('COMPLETE_FLAT',s.closedTrades,'No more entries, including reversal leg');}
                    if(!s.complete && decision.direction)leg(decision.direction*qty,decision.reason);
                    s.intent=null;save();
                }
            }
            if(env.draw&&c.showLines)env.draw(f);
        }
        save();var status={mode:c.live?'LIVE':'PAPER_NO_ORDERS',complete:s.complete,net:s.net,avg:s.avg,
            closedTrades:s.closedTrades,estimatedPnL:s.estimatedPnL,frame:engine.state().frame,lastSignal:s.lastSignal,lastBlocked:s.lastBlocked};
        env.status(JSON.stringify(status));return status;
    }
    save();return {step:step,state:function(){return JSON.parse(JSON.stringify(s));}};
}
function main(){
    var c={live:typeof AF_RUN_MODE!=='undefined'&&AF_RUN_MODE===1,sizeMode:typeof AF_SIZE_MODE==='undefined'?1:AF_SIZE_MODE,
        fixedContracts:typeof AF_FIXED_CONTRACTS==='undefined'?1:AF_FIXED_CONTRACTS,equityPct:typeof AF_EQUITY_PCT==='undefined'?10:AF_EQUITY_PCT,
        cap:typeof AF_APPROVED_CAP==='undefined'?1:AF_APPROVED_CAP,maxRoundTrips:typeof AF_MAX_ROUND_TRIPS==='undefined'?1:AF_MAX_ROUND_TRIPS,
        showLines:typeof AF_SHOW_LINES==='undefined'?true:AF_SHOW_LINES};
    if(typeof AF_RUN_MODE!=='undefined'&&[0,1].indexOf(AF_RUN_MODE)<0)throw Error('Invalid execution mode');
    if(typeof exchange==='undefined'||!exchange||typeof exchanges!=='undefined'&&exchanges.length!==1)throw Error('Attach exactly one Spartans account');
    var label=exchange.GetLabel(),expected=typeof AF_ACCOUNT_LABEL==='undefined'?'OneBullEx-Spartans':AF_ACCOUNT_LABEL;
    if(typeof expected!=='string'||!expected.trim()||label!==expected)throw Error('Select the configured Spartans account');
    var key='alligator-fractal-public-v1:'+label+':'+exchange.GetCurrency()+':'+(c.live?'LIVE':'PAPER'),chart=null;
    try{
        var r=createAlligatorRuntime({exchange:exchange,now:function(){return Date.now();},sleep:Sleep,
            loadState:function(){return _G(key);},saveState:function(s){_G(key,s);},loadJournal:function(){return _G(key+':order');},saveJournal:function(j){_G(key+':order',j);},
            log:function(){Log.apply(null,arguments);},status:LogStatus,
            draw:function(f){if(!chart)chart=Chart({title:{text:'Alligator / confirmed fractals'},xAxis:{type:'datetime'},series:[{name:'Jaw (shift 8)',data:[]},{name:'Teeth (shift 5)',data:[]},{name:'Lips (shift 3)',data:[]},{name:'Confirmed high',data:[]},{name:'Confirmed low',data:[]}]});[f.jaw,f.teeth,f.lips,f.high,f.low].forEach(function(v,i){chart.add(i,[f.time,v]);});}
        },c);
        Log(c.live?'LIVE_USER_APPROVED':'PAPER_NO_ORDERS',JSON.stringify(c),'1m closed-bar signals; no exchange-native stop; fees in PnL are estimates');
        while(true){var status=r.step();if(status.complete)break;Sleep(5000);}
    }catch(e){LogStatus('STOPPED: '+String(e)+'. Reconcile account/journal. Host-managed exits offline.');Log('STOPPED',String(e));throw e;}
}
if(typeof module!=='undefined'&&module.exports)module.exports={createAlligatorRuntime:createAlligatorRuntime};
