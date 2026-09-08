/* GlowBright — bundled, dependency-free Home Assistant panel. MIT. */
const TZ = "Europe/London";
const PERIODS = [["PT30M", "30 min"], ["PT1H", "Hour"], ["P1D", "Day"], ["P1W", "Week"], ["P1M", "Month"]];
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const number = value => value == null ? "—" : Number(value).toLocaleString("en-GB", {maximumFractionDigits: 3});
const localDate = value => new Intl.DateTimeFormat("en-CA", {timeZone: TZ, year:"numeric", month:"2-digit", day:"2-digit"}).format(new Date(value));
const displayTime = value => value ? new Intl.DateTimeFormat("en-GB", {timeZone: TZ, day:"numeric", month:"short", hour:"2-digit", minute:"2-digit", timeZoneName:"short"}).format(new Date(value)) : "Awaiting data";

// Calendar arithmetic uses date components; only boundaries become UTC instants.
function shiftDate(date, days = 0, months = 0) {
  const [y,m,d] = date.split("-").map(Number);
  return new Date(Date.UTC(y,m - 1 + months,d + days)).toISOString().slice(0,10);
}
function londonMidnight(date) {
  const target = Date.parse(`${date}T00:00:00Z`);
  let instant = target;
  for (let i=0; i<3; i++) {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {timeZone:TZ, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"}).formatToParts(new Date(instant)).map(p => [p.type,p.value]));
    const rendered = Date.UTC(+parts.year,+parts.month-1,+parts.day,+parts.hour,+parts.minute,+parts.second);
    instant += target - rendered;
  }
  return new Date(instant).toISOString();
}
function rangeFor(date, period) {
  let start=date, end=shiftDate(date,1);
  if (period === "P1D" || period === "P1W") {
    const weekday = (new Date(`${date}T12:00:00Z`).getUTCDay()+6)%7;
    start=shiftDate(date,-weekday);
    if (period === "P1W") start=shiftDate(start,-49);
    end=shiftDate(start,period === "P1D" ? 7 : 56);
  } else if (period === "P1M") {
    start=`${date.slice(0,4)}-01-01`; end=shiftDate(start,0,12);
  }
  return {start:londonMidnight(start),end:londonMidnight(end),localStart:start,localEnd:end};
}

class GlowBrightPanel extends HTMLElement {
  constructor() {
    super(); this.attachShadow({mode:"open"});
    this.fuel="electricity"; this.metric="usage"; this.period="PT30M";
    this.date=localDate(Date.now()); this.accounts=[]; this.request=0;
  }
  set hass(value) { this._hass=value; if (this.isConnected && !this.started) this.start(); }
  connectedCallback() {
    this.resizeObserver = new ResizeObserver(() => {
      const compact = this.getBoundingClientRect().width < 650;
      if (compact !== this.compact) { this.compact = compact; this.render(); }
    });
    this.resizeObserver.observe(this);
    if (this._hass && !this.started) this.start();
  }
  disconnectedCallback() { clearInterval(this.timer); this.resizeObserver?.disconnect(); this.started=false; this.request++; }
  start() { this.started=true; this.render(); this.load(true); this.timer=setInterval(()=>this.load(),60000); }
  get account() { return this.accounts.find(a=>a.entry_id===this.entryId); }
  get fuelStatus() { return this.account?.fuels?.[this.fuel]; }
  async load(initial=false) {
    const request=++this.request;
    this.loading=true; this.error=""; this.render();
    try {
      const status=await this._hass.callWS({type:"glowbright/get_status"});
      if (request!==this.request) return;
      this.accounts=status.accounts;
      if (!this.accounts.some(a=>a.entry_id===this.entryId)) this.entryId=this.accounts[0]?.entry_id;
      if (!this.account) { this.series=null; this.loading=false; this.render(); return; }
      if (!this.fuelStatus) this.fuel=Object.keys(this.account.fuels)[0];
      if (!this.fuel) throw new Error("No accessible meter resources.");
      if (!this.fuelStatus.cost_available) this.metric="usage";
      if (initial && this.fuelStatus.latest_reading) this.date=localDate(this.fuelStatus.latest_reading);
      const range=rangeFor(this.date,this.period);
      const command={type:"glowbright/get_series",entry_id:this.entryId,fuel:this.fuel,period:this.period,start:range.start,end:range.end};
      const [usage,cost]=await Promise.all([this._hass.callWS({...command,metric:"usage"}),this.fuelStatus.cost_available ? this._hass.callWS({...command,metric:"cost"}).catch(()=>null) : null]);
      if (request!==this.request) return;
      this.series={usage,cost}; this.range=range;
    } catch (error) { if (request===this.request) this.error=error.message || "Data temporarily unavailable. Try again shortly."; }
    if (request===this.request) { this.loading=false; this.render(); }
  }
  async change(key,value) { this[key]=value; this.series=null; await this.load(); }
  navigate(direction) {
    const days=this.period==="P1D" ? 7 : this.period==="P1W" ? 56 : 1;
    this.change("date",this.period==="P1M" ? shiftDate(this.date,0,12*direction) : shiftDate(this.date,days*direction));
  }
  bins() {
    if (!this.range) return [];
    const bins=[];
    if (["PT30M","PT1H"].includes(this.period)) {
      const step=this.period==="PT30M" ? 1800000 : 3600000;
      for(let t=Date.parse(this.range.start);t<Date.parse(this.range.end);t+=step) bins.push(new Date(t).toISOString());
    } else {
      for(let d=this.range.localStart;d<this.range.localEnd;d=shiftDate(d,this.period==="P1D"?1:this.period==="P1W"?7:0,this.period==="P1M"?1:0)) bins.push(londonMidnight(d));
    }
    return bins;
  }
  label(stamp) {
    if (["PT30M","PT1H"].includes(this.period)) return new Intl.DateTimeFormat("en-GB",{timeZone:TZ,hour:"2-digit",minute:"2-digit",timeZoneName:"short"}).format(new Date(stamp));
    return new Intl.DateTimeFormat("en-GB",{timeZone:TZ,day:this.period==="P1M"?undefined:"numeric",month:"short",year:"numeric"}).format(new Date(stamp));
  }
  chart(data) {
    const bins=this.bins(); if (!bins.length) return "";
    const values=new Map((data?.rows||[]).map(r=>[Date.parse(r.start),r.value]));
    const max=Math.max(...values.values(),0.001); const compact=this.getBoundingClientRect().width<650; const width=compact?360:960,height=compact?220:255,left=54,bottom=30,plot=width-left-12;
    const step=plot/bins.length;
    const grid=[0,.25,.5,.75,1].map(f=>{const y=height-bottom-f*(height-bottom-15); return `<line x1="${left}" y1="${y}" x2="${width-12}" y2="${y}" class="grid"/><text x="44" y="${y+4}" text-anchor="end">${number(max*f)}</text>`;}).join("");
    const bars=bins.map((stamp,i)=>{const value=values.get(Date.parse(stamp)); const x=left+i*step+2; const y=height-bottom-(value||0)/max*(height-bottom-15); return value==null ? `<line x1="${x}" x2="${x+Math.max(1,step-4)}" y1="${height-bottom+3}" y2="${height-bottom+3}" class="missing"><title>${escapeHTML(this.label(stamp))}: missing data</title></line>` : `<rect x="${x}" y="${y}" width="${Math.max(1,step-4)}" height="${Math.max(1,height-bottom-y)}" rx="2" class="bar"><title>${escapeHTML(this.label(stamp))}: ${number(value)} ${escapeHTML(data.unit)}</title></rect>`;}).join("");
    const ticks=bins.filter((_,i)=>i%Math.max(1,Math.ceil(bins.length/(compact?3:6)))===0).map(stamp=>{const i=bins.indexOf(stamp);return `<text x="${left+i*step+step/2}" y="${height-3}" text-anchor="middle">${escapeHTML(this.label(stamp))}</text>`;}).join("");
    return `<svg role="img" aria-label="${this.metric} by ${escapeHTML(PERIODS.find(p=>p[0]===this.period)[1])}; missing intervals are marked by dashed lines. Full values in table." viewBox="0 0 ${width} ${height}">${grid}${bars}${ticks}</svg>`;
  }
  render() {
    const fuel=this.fuelStatus || {}; const data=this.series?.[this.metric];
    const age=fuel.data_age_hours; const stale=age==null || age>24;
    const usageMap=new Map((this.series?.usage?.rows||[]).map(r=>[Date.parse(r.start),r.value]));
    const costMap=new Map((this.series?.cost?.rows||[]).map(r=>[Date.parse(r.start),r.value]));
    this.shadowRoot.innerHTML=`<style>
      :host{display:block;height:100%;overflow:auto;background:var(--primary-background-color,#f4f7f9);color:var(--primary-text-color,#1d3342);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
      *{box-sizing:border-box} header{display:flex;align-items:center;gap:14px;padding:18px 24px;background:var(--card-background-color,#fff);border-bottom:1px solid var(--divider-color,#dde5eb)}
      .mark{display:grid;place-items:center;width:36px;height:36px;border-radius:12px;background:#123d50;color:#ffcc57;font-size:24px}h1{font-size:21px;margin:0;letter-spacing:-.6px}header p{margin:2px 0 0;font-size:12px;color:var(--secondary-text-color,#607580)}
      main{max-width:1130px;margin:auto;padding:28px 24px 48px}.top{display:flex;gap:18px;align-items:end;justify-content:space-between;margin-bottom:22px}h2{font-size:28px;letter-spacing:-.8px;margin:0 0 6px}.muted{color:var(--secondary-text-color,#687c86);font-size:13px;margin:0}
      button,select,input{font:inherit;color:inherit;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#d5e0e5);border-radius:9px;padding:10px 13px;min-height:42px}button{cursor:pointer}button:hover{border-color:var(--primary-color,#168a8b)}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid var(--primary-color,#168a8b);outline-offset:2px}button:disabled{opacity:.4;cursor:default}.segments{display:flex;gap:4px;background:var(--secondary-background-color,#e8eef1);padding:4px;border-radius:12px}.segments button{border:0;background:transparent;font-size:14px}.segments button.selected{background:var(--card-background-color,#fff);box-shadow:0 2px 5px #0001;font-weight:650;color:var(--primary-color,#117e80)}
      .freshness{padding:17px 20px;border:1px solid var(--divider-color,#d5e0e5);border-radius:14px;background:var(--card-background-color,#fff);display:flex;gap:22px;justify-content:space-between;align-items:center;margin-bottom:20px}.freshness.stale{border-left:5px solid #c88912}.freshness strong{display:block;font-size:14px;margin-bottom:5px}.freshness p{font-size:13px;margin:0;line-height:1.6}.badge{white-space:nowrap;border-radius:20px;background:#b778111a;color:var(--primary-text-color,#79580c);padding:8px 12px;font-size:12px;font-weight:650}
      .card{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#dde5eb);border-radius:17px;padding:24px}.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:14px;justify-content:space-between}.nav{display:flex;align-items:center;gap:7px}.total{margin:28px 0 4px;font-size:38px;font-weight:650;letter-spacing:-1.3px}.total small{font-size:18px;font-weight:400;letter-spacing:0}.coverage{font-size:12px;color:var(--secondary-text-color,#687c86);margin-bottom:24px}.chart{width:100%;margin:16px 0 10px;min-height:180px}.chart svg{width:100%;display:block;overflow:visible}.chart text{font:11px system-ui;fill:var(--secondary-text-color,#687c86)}.grid{stroke:var(--divider-color,#dde5eb);stroke-width:1}.bar{fill:var(--primary-color,#19888b)}.missing{stroke:#b78635;stroke-dasharray:3 2;stroke-width:2}.legend{font-size:12px;color:var(--secondary-text-color,#687c86);margin:12px 0 0}
      .summary{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:20px 0}.summary .card{padding:19px}.summary dt{font-size:12px;color:var(--secondary-text-color,#687c86);margin-bottom:8px}.summary dd{font-size:19px;margin:0;font-weight:600}.summary small{font-size:12px;font-weight:400}.table-wrap{max-height:390px;overflow:auto;margin-top:15px}table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--secondary-text-color,#687c86);font-size:12px;background:var(--card-background-color,#fff);position:sticky;top:0}td,th{padding:13px 10px;border-bottom:1px solid var(--divider-color,#dde5eb)}td:not(:first-child),th:not(:first-child){text-align:right}.error{padding:14px;border:1px solid #d8954a;border-radius:10px;margin:14px 0;font-size:14px}.empty{padding:42px 10px;text-align:center;color:var(--secondary-text-color,#687c86)}.footer{font-size:12px;line-height:1.7;margin-top:20px;color:var(--secondary-text-color,#687c86)}
      @media(max-width:650px){main{padding:20px 12px}.top{align-items:start;flex-direction:column}h2{font-size:25px}.card{padding:16px}.toolbar{align-items:stretch}.segments{flex-wrap:wrap}.segments button{padding:9px 10px}.summary{grid-template-columns:1fr;gap:10px}.summary .card{padding:15px}.summary dt{display:inline-block;width:48%;margin:0}.summary dd{display:inline-block}.freshness{gap:12px;align-items:start;flex-direction:column}.total{font-size:32px}.nav{width:100%;justify-content:space-between}header{padding:13px}.chart{min-height:100px}input{max-width:170px}}
    </style><header><button id="menu" aria-label="Open sidebar">☰</button><span class="mark" aria-hidden="true">ϟ</span><div><h1>GlowBright</h1><p>Your energy, in its own time.</p></div></header><main>
      <div class="top"><div><h2>Your energy history</h2><p class="muted">Bright DCC smart-meter readings · Europe/London</p></div><div class="segments" role="group" aria-label="Fuel">${["electricity","gas"].map(f=>`<button data-fuel="${f}" class="${this.fuel===f?"selected":""}" aria-pressed="${this.fuel===f}" ${!this.account?.fuels?.[f]?"disabled":""}>${f==="electricity"?"Electricity":"Gas"}</button>`).join("")}</div></div>
      ${this.accounts.length>1?`<label>Bright account <select id="account">${this.accounts.map(a=>`<option value="${escapeHTML(a.entry_id)}" ${a.entry_id===this.entryId?"selected":""}>${escapeHTML(a.title)} · ${escapeHTML(a.entry_id.slice(-5))}</option>`).join("")}</select></label>`:""}
      <section class="freshness ${stale?"stale":""}" aria-label="Data freshness"><div><strong>Latest DCC data: ${escapeHTML(displayTime(fuel.latest_reading))}</strong><p>${stale?"Readings are delayed. The latest dates may be incomplete.":"DCC readings can arrive or change 24–48 hours later."} Missing intervals are not zero usage.</p></div><span class="badge">${age==null?"Awaiting readings":`${number(Number(age.toFixed(1)))} hours old`}</span></section>
      ${this.error?`<div class="error" role="alert">${escapeHTML(this.error)} <button id="retry">Retry</button></div>`:""}
      ${this.account?.api_error?`<div class="error">Glowmarkt is temporarily unavailable. Showing last-good imported data.</div>`:""}
      <section class="card" aria-busy="${this.loading}"><div class="toolbar"><div class="segments" aria-label="Metric">${["usage","cost"].map(m=>`<button data-metric="${m}" class="${this.metric===m?"selected":""}" aria-pressed="${this.metric===m}" ${m==="cost"&&!fuel.cost_available?"disabled":""}>${m==="usage"?"Usage":"Cost"}</button>`).join("")}</div><div class="segments" aria-label="Graph period">${PERIODS.map(([p,l])=>`<button data-period="${p}" class="${this.period===p?"selected":""}" aria-pressed="${this.period===p}">${l}</button>`).join("")}</div></div>
      <div class="total">${data?number(data.total):"—"} <small>${escapeHTML(data?.unit || (this.metric==="cost"?"GBP":fuel.unit||"kWh"))}</small></div><div class="coverage">${this.loading?"Loading historical readings…":data?`${number(data.coverage_hours)} of ${number(data.requested_hours)} hours available${data.cached?" · cached API readings":""}. ${data.coverage_hours<data.requested_hours?"Partial period total.":"Full period coverage."}`:"No readings available for this period."}</div>
      <div class="nav"><button id="previous" aria-label="Previous date range">←</button><label><span class="muted">Selected date </span><input id="date" type="date" value="${this.date}" aria-label="Selected London date"></label><button id="next" aria-label="Next date range">→</button></div>
      <div class="chart">${this.chart(data)}</div><p class="legend">Dashed marks = readings not yet available. Hover over a bar for its value.</p></section>
      <dl class="summary"><div class="card"><dt>Current unit rate</dt><dd>${number(fuel.tariff?.unit_rate)} <small>p/kWh</small></dd></div><div class="card"><dt>Standing charge</dt><dd>${number(fuel.tariff?.standing_charge)} <small>p/day</small></dd></div><div class="card"><dt>Last API update</dt><dd style="font-size:15px">${escapeHTML(displayTime(this.account?.last_api_update))}</dd></div></dl>
      <section class="card"><strong>Period breakdown</strong><div class="table-wrap"><table><thead><tr><th scope="col">${["PT30M","PT1H"].includes(this.period)?"Time (UK)":"Period beginning"}</th><th scope="col">Usage (${escapeHTML(fuel.unit||"kWh")})</th>${fuel.cost_available?"<th scope=\"col\">Usage cost (£)</th>":""}</tr></thead><tbody>${this.bins().map(stamp=>`<tr><td>${escapeHTML(this.label(stamp))}</td><td>${number(usageMap.get(Date.parse(stamp)))}</td>${fuel.cost_available?`<td>${number(costMap.get(Date.parse(stamp)))}</td>`:""}</tr>`).join("")}</tbody></table></div></section>
      <p class="footer">${escapeHTML(fuel.resource?.ve_name||"")} · ${escapeHTML(fuel.resource?.resource_name||"")}<br>Costs are API-supplied historical usage costs and exclude standing charge. ${fuel.estimated_conversion?"Gas energy is an estimate converted from meter volume.":""} ${fuel.tariff_error?"Tariff temporarily unavailable; showing the last successful tariff.":""}<br>GlowBright is an independent integration, unaffiliated with Hildebrand.</p>
    </main>`;
    this.shadowRoot.querySelector("#menu").onclick=()=>this.dispatchEvent(new CustomEvent("hass-toggle-menu",{bubbles:true,composed:true}));
    for (const key of ["fuel","metric","period"]) this.shadowRoot.querySelectorAll(`[data-${key}]`).forEach(button=>button.onclick=()=>this.change(key,button.dataset[key]));
    this.shadowRoot.querySelector("#previous").onclick=()=>this.navigate(-1);
    this.shadowRoot.querySelector("#next").onclick=()=>this.navigate(1);
    this.shadowRoot.querySelector("#date").onchange=event=>{if(event.target.value) this.change("date",event.target.value);};
    const account=this.shadowRoot.querySelector("#account"); if(account) account.onchange=event=>this.change("entryId",event.target.value);
    const retry=this.shadowRoot.querySelector("#retry"); if(retry) retry.onclick=()=>this.load();
  }
}
if (!customElements.get("glowbright-panel")) customElements.define("glowbright-panel",GlowBrightPanel);
export {rangeFor, londonMidnight};
