const fs = require('fs');
const FR = require('../web/assets/focus-round.js');
const DT = 0.05, JUMP = 2.0;
function seeded(seed){let s=seed>>>0;return()=>{s=(s*1664525+1013904223)>>>0;return s/4294967296;};}
function sim(scoreAt, seconds, reaction, seed, startEnergy, zoneLoMin, zoneLoMax){
  const rng=seeded(seed);
  const cfg={startEnergy, zoneLoMin, zoneLoMax, firstRoundLoMin:zoneLoMin, firstRoundLoMax:zoneLoMax};
  const e=new FR.RoundEngine(cfg, rng, {firstRound:false});
  let t=0,jumpAge=0;
  while(t<seconds){
    if(e.phase==='JUMP_SUCCESS'||e.phase==='JUMP_MISSED'){
      jumpAge+=DT;
      if(jumpAge>=JUMP){jumpAge=0;e.finishRound();}
      t+=DT; continue;
    }
    const score=scoreAt(t);
    if(e.phase==='BULLET_TIME'){
      e.update(DT,{signalOk:true,charging:false,score});
      if(e.phase==='BULLET_TIME'&&e.bulletElapsed>=reaction)e.tap();
    }else{
      const evs=e.update(DT,{signalOk:true,charging:score>FR.CONFIG.chargeZeroScore,score});
      for(const ev of evs){if(ev.type==='bullet_enter'&&reaction<=0)e.tap();}
    }
    t+=DT;
  }
  if(e.phase==='JUMP_SUCCESS'||e.phase==='JUMP_MISSED')e.finishRound();
  const total=e.records.reduce((a,r)=>a+(r.awarded||0),0);
  const charge=e.records.reduce((a,r)=>a+r.charge_sec,0);
  return {rounds:e.records.length,total,coins:FR.pointsForScore(total),
          charge:+charge.toFixed(2), avgCharge: e.records.length ? +(charge/e.records.length).toFixed(2) : 0};
}
const profiles=[['低专注 48',()=>48],['偏低 55',()=>55],['典型 60',()=>60],['基准 65',()=>65],['良好 70',()=>70],['高 85',()=>85],['间歇 70/45',t=>((t%8)<4?70:45)]];
const rows=[];
for(const sec of [60,180,300]){
  for(const [name,fn] of profiles){
    const a=sim(fn,sec,0.8,20261128,15,24,55);
    const b=sim(fn,sec,0.8,20261128,10,24,55);
    rows.push({kind:'start_energy',seconds:sec,profile:name,difficulty:1,
      rounds15:a.rounds,score15:a.total,coins15:a.coins,charge15:a.charge,avg_charge15:a.avgCharge,
      rounds10:b.rounds,score10:b.total,coins10:b.coins,charge10:b.charge,avg_charge10:b.avgCharge,
      coin_delta:+(b.coins-a.coins).toFixed(0), coin_delta_pct:+(((b.coins/(a.coins||1))-1)*100).toFixed(1)});
  }
}
for(const factor of [0.6,1.0,1.2]){
  const lo=24*factor, hi=55*factor;
  const a=sim(()=>65,180,0.8,20261128,15,lo,hi);
  const b=sim(()=>65,180,0.8,20261128,10,lo,hi);
  rows.push({kind:'difficulty',seconds:180,profile:'基准 65',difficulty:factor,
    rounds15:a.rounds,score15:a.total,coins15:a.coins,charge15:a.charge,avg_charge15:a.avgCharge,
    rounds10:b.rounds,score10:b.total,coins10:b.coins,charge10:b.charge,avg_charge10:b.avgCharge,
    coin_delta:+(b.coins-a.coins).toFixed(0), coin_delta_pct:+(((b.coins/(a.coins||1))-1)*100).toFixed(1)});
}
fs.writeFileSync(require('path').join(__dirname, '..', 'outputs', 'v1.9.4', 'economy-10-vs-15.json'), JSON.stringify({rows, meta:{sim_dt:DT,jump_sec:JUMP,reaction_sec:0.8,seed:20261128}},null,2));
console.log(JSON.stringify(rows.slice(0,14),null,0));
