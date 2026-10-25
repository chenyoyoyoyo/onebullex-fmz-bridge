// SPDX-License-Identifier: MPL-2.0
/* Execution module for Spartans strategy examples. No independent main().
 * Included by build.js; controlled by the runtime execution mode.
 * Live trading is disabled unless explicitly enabled by its caller.
 * Uses only the bridge's supported query and Buy/Sell interfaces.
 */
function createSpartansExecution(env, options) {
    "use strict";
    var ex = env.exchange;
    // maxOrderContracts: optional per-order guard chosen by the user; 0 = no limit.
    var cfg = Object.assign({liveEnabled: false, maxOrderContracts: 0,
        timeoutMs: 15000, pollMs: 1000, symbol: null}, options || {});
    if (!cfg.symbol) cfg.symbol = ex.GetCurrency();   // e.g. BTC_USDT or BTCSPARTANS_USDT
    var obSymbol = String(cfg.symbol).toLowerCase();
    var busy = false;
    if (!Number.isSafeInteger(cfg.maxOrderContracts) || cfg.maxOrderContracts < 0)
        throw new Error("Invalid single-order limit");
    // Exchange names may differ only by underscores (btcspartans_usdt vs btcspartansusdt).
    function sameSymbol(a, b) {
        return String(a).replace(/_/g, "").toLowerCase() === String(b).replace(/_/g, "").toLowerCase();
    }
    function fail(message) { throw new Error(message); }
    function number(value, name) {
        if (value === null || value === undefined || value === "" ||
            typeof value === "boolean") fail("Missing " + name);
        var n = Number(value);
        if (!Number.isFinite(n)) fail("Invalid " + name);
        return n;
    }
    function integer(n, name) {
        n = number(n, name);
        if (!Number.isSafeInteger(n)) fail(name + " must be integer contracts");
        return n;
    }
    function data(path, query) {
        var r = ex.IO("api", "GET", path, query || "");
        if (typeof r === "string") r = JSON.parse(r);
        if (!r || !Object.prototype.hasOwnProperty.call(r, "data") || r.data == null)
            fail("Query failed: " + path);
        return r.data;
    }
    function position() {
        var rows = data("/v2/position/list", "symbol=" + obSymbol);
        if (!Array.isArray(rows)) fail("Positions must be an array");
        var active = [];
        rows.forEach(function (p) {
            if (!sameSymbol(p.symbol, obSymbol)) fail("Unexpected position symbol");
            var size = integer(p.positionSize, "positionSize");
            if (size < 0) fail("Negative position size");
            if (size) {
                if (p.positionSide !== "LONG" && p.positionSide !== "SHORT")
                    fail("Unknown position side");
                active.push(p);
            }
        });
        if (active.length > 1) fail("Multiple positions: operator reconciliation required");
        if (!active.length) return {net: 0, row: null};
        var p = active[0];
        return {net: Number(p.positionSize) * (p.positionSide === "LONG" ? 1 : -1), row: p};
    }
    function spec() {
        var s = data("/v2/public/symbol/detail", "symbol=" + obSymbol);
        var size = number(s.contractSize, "contractSize");
        var minQty = number(s.minQty, "minQty");
        // Contract size differs per symbol (read it, never assume BTC_USDT's 0.0001).
        if (!sameSymbol(s.symbol, obSymbol) || !(size > 0) ||
            number(s.quantityPrecision, "quantityPrecision") !== 0 ||
            !Number.isSafeInteger(minQty) || minQty < 1) fail("Unexpected contract specification");
        return {contractSize: size, minQty: minQty, priceStep: number(s.minStepPrice, "minStepPrice")};
    }
    // Explicit equity argument: caller must supply audited futures equity, not funding
    // balance or Pine strategy.equity, whose live semantics are not yet validated.
    function sizeForRisk(entry, stop, equity, riskUSDT, exposureMultiple, stepBTC) {
        entry = number(entry, "entry"); stop = number(stop, "stop");
        equity = number(equity, "equity"); riskUSDT = number(riskUSDT, "riskUSDT");
        exposureMultiple = number(exposureMultiple, "exposureMultiple");
        stepBTC = number(stepBTC, "stepBTC");
        if (entry <= 0 || stop <= 0 || equity <= 0 || riskUSDT <= 0 ||
            exposureMultiple <= 0 || stepBTC <= 0 || entry === stop)
            fail("Invalid risk inputs");
        var unit = spec().contractSize;
        var stepContracts = Math.round(stepBTC / unit);
        if (stepContracts < 1 || Math.abs(stepContracts * unit - stepBTC) > 1e-12)
            fail("Size step must be a whole number of contracts");
        var distance = Math.abs(entry - stop);
        var rawBTC = Math.min(riskUSDT / distance, equity * exposureMultiple / entry);
        var lots = Math.floor(rawBTC / stepBTC + 1e-10);
        var contracts = lots * stepContracts;
        // Correct floating-point boundary cases without increasing either budget.
        while (contracts > 0 && (contracts * unit * distance > riskUSDT + 1e-9 ||
                contracts * unit * entry > equity * exposureMultiple + 1e-9))
            contracts -= stepContracts;
        return {contracts: contracts, btc: contracts * unit,
            estimatedStopLossUSDT: contracts * unit * distance,
            notionalUSDT: contracts * unit * entry,
            exceedsSingleOrderLimit: cfg.maxOrderContracts > 0 && contracts > cfg.maxOrderContracts,
            includesFeesAndSlippage: false};
    }
    function pendingOrders() {
        var r = ex.GetOrders();
        if (!Array.isArray(r)) fail("Open-order query failed");
        return r;
    }
    function checkQuantity(q) {
        integer(q, "order quantity");
        if (q < 1) fail("Quantity below one contract");
        if (cfg.maxOrderContracts > 0 && q > cfg.maxOrderContracts)
            fail("Exceeds the single-order limit set in parameters; no order splitting");
    }
    function plan(target) {
        target = integer(target, "target");
        if (ex.GetCurrency() !== cfg.symbol) fail("Wrong FMZ currency");
        spec();
        if (pendingOrders().length) fail("Existing open orders: stop and reconcile");
        var net = position().net;
        var actions = [];
        if (net === target) return actions;
        if (net && target && Math.sign(net) !== Math.sign(target)) {
            actions.push({side: net > 0 ? "Sell" : "Buy", qty: Math.abs(net),
                from: net, to: 0, purpose: "close"});
            actions.push({side: target > 0 ? "Buy" : "Sell", qty: Math.abs(target),
                from: 0, to: target, purpose: "open"});
        } else {
            var delta = target - net;
            actions.push({side: delta > 0 ? "Buy" : "Sell", qty: Math.abs(delta),
                from: net, to: target, purpose: Math.abs(target) < Math.abs(net) ? "close" : "open"});
        }
        // Preflight ALL legs, including reversal, before sending any leg.
        actions.forEach(function (a) { checkQuantity(a.qty); });
        return actions;
    }
    // Optional: set leverage through the bridge (FMZ SetMarginLevel is not forwarded).
    function setLeverage(n) {
        n = integer(n, "leverage");
        if (n < 1) fail("Leverage must be at least 1");
        var r = ex.IO("api", "POST", "/v2/position/adjust-leverage", "symbol=" + obSymbol + "&leverage=" + n);
        if (typeof r === "string") r = JSON.parse(r);
        if (!r || Number(r.data) !== n) fail("Leverage not confirmed");
        return n;
    }
    function moveTo(target) {
        if (busy) fail("Execution already in progress");
        if (cfg.liveEnabled && (!env.load || !env.save)) fail("Durable journal required");
        if (cfg.liveEnabled && env.load()) fail("Unresolved journal: operator reconciliation required");
        var actions = plan(target);
        if (!cfg.liveEnabled) return {dryRun: true, actions: actions};
        busy = true;
        var fills = [];
        try {
            actions.forEach(function (a) {
                if (pendingOrders().length || position().net !== a.from)
                    fail("Account changed before send");
                // Persist BEFORE the network request. A timeout/false ID must never
                // cause an automatic retry with a fresh server-generated order ID.
                env.save({state: "sending", action: a, at: env.now()});
                var id = ex[a.side](-1, a.qty);
                if (!id) fail("Unknown submission outcome; inspect journal and account");
                env.save({state: "submitted", action: a, id: id, at: env.now()});
                var deadline = env.now() + cfg.timeoutMs;
                var filled = false;
                while (env.now() < deadline) {
                    env.sleep(cfg.pollMs);
                    var o = ex.GetOrder(id);
                    if (!o) continue;
                    if (Number(o.Amount) !== a.qty) fail("Order quantity mismatch");
                    if (Number(o.DealAmount) > a.qty) fail("Unexpected fill quantity");
                    if (Number(o.Status) === 2) fail("Order canceled or partially filled; reconcile");
                    if (Number(o.Status) === 1 && Number(o.DealAmount) === a.qty) {
                        var fillPrice = number(o.AvgPrice, "confirmed AvgPrice");
                        if (fillPrice <= 0) fail("Missing actual fill price; reconcile");
                        fills.push({id:id, side:a.side, qty:a.qty, price:fillPrice, purpose:a.purpose});
                        filled = true;
                        break;
                    }
                }
                if (!filled) fail("Fill not confirmed; journal retained, no retry");
                var synced = false;
                deadline = env.now() + cfg.timeoutMs;
                while (env.now() < deadline) {
                    if (position().net === a.to) { synced = true; break; }
                    env.sleep(cfg.pollMs);
                }
                if (!synced) fail("Position not synchronized; no next order");
                if (pendingOrders().length) fail("Unexpected open order after fill");
                env.save(null);
                if (env.log) env.log("Confirmed", id, a.purpose, a.to);
            });
            return {dryRun: false, net: position().net, fills:fills};
        } finally { busy = false; }
    }
    return {position: position, spec: spec, sizeForRisk: sizeForRisk,
        plan: plan, moveTo: moveTo, setLeverage: setLeverage, symbol: obSymbol};
}
if (typeof module !== "undefined" && module.exports)
    module.exports = {createSpartansExecution: createSpartansExecution};
