// Drives pointStakes() -- lifted verbatim from the shared match viewer -- over
// real simulated matches, so the stake labels are checked against the engine
// that produced the points rather than against a hand-written fixture.
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');

eval(fs.readFileSync(path.join(ROOT, 'simulation/engine.js'), 'utf8')
  + '\nglobalThis.simulateTournament = simulateTournament;');

// Brace-match the two functions out of the shipped file so the test cannot
// drift from what the pages actually load.
const tpl = fs.readFileSync(path.join(ROOT, 'simulation/matchview.js'), 'utf8');
function lift(name){
  const start = tpl.indexOf('function ' + name + '(');
  if(start < 0) throw new Error(name + ' not found in simulation/matchview.js');
  let depth = 0;
  for(let i = tpl.indexOf('{', start); i < tpl.length; i++){
    if(tpl[i] === '{') depth++;
    else if(tpl[i] === '}' && --depth === 0) return tpl.slice(start, i + 1);
  }
  throw new Error(name + ' is unbalanced');
}
// ladder needs LADDER_PT, which lives beside it.
const LADDER_PT = ['0', '15', '30', '40'];
eval(lift('pointStakes') + '\n' + lift('ladder')
  + '\nglobalThis.pointStakes = pointStakes; globalThis.ladder = ladder;');

const pool = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = { games: 0, stakes: 0, ends: 0, rows: [] };
for(let s = 0; s < Number(process.argv[3] || 6); s++){
  const r = simulateTournament(pool, { seed: 500 + s, playable: null, tour: 'ATP',
                                       surface: 'hard', drawSize: 32,
                                       bestOf: 3, finalSetTiebreak: 7 });
  r.rounds.forEach(rd => rd.matches.forEach(m => {
    if(!m.sets || !m.sets.length) return;
    const stakes = pointStakes(m, { bestOf: 3, decidingTiebreak: 7 });
    m.sets.forEach((set, si) => set.g.forEach((g, gi) => {
      out.games++;
      const n = g.pts.length;
      // Points won by each side after each point -- taken straight from the
      // match record, not from anything pointStakes computed.
      const runs = [];
      let a = 0, b = 0;
      g.pts.forEach(p => { if(p[0] === 0) a++; else b++; runs.push([a, b]); });
      const tb = g.k === 't';
      for(let i = 0; i < n; i++){
        const e = stakes.get(si + ':' + gi + ':' + i) || {};
        if(e.stake) out.stakes++;
        if(e.end) out.ends++;
        // Is `side` exactly one point from the game, on the score AFTER point i?
        const oneAway = side => {
          const mine = runs[i][side], theirs = runs[i][1 - side];
          const need = tb ? 7 : 4;
          return mine + 1 >= need && mine + 1 - theirs >= 2;
        };
        out.rows.push({
          i, last: i === n - 1, tb, srv: g.srv,
          stake: e.stake ? e.stake.kind : null,
          stakeSide: e.stake ? e.stake.side : null,
          end: e.end ? e.end.kind : null,
          oneAway0: oneAway(0), oneAway1: oneAway(1),
          prevStake: i > 0 ? ((stakes.get(si + ':' + gi + ':' + (i - 1)) || {}).stake || {}).kind || null : null,
        });
      }
    }));
  }));
}
console.log(JSON.stringify(out));
