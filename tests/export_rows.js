// Drives exportRows() -- lifted verbatim from the page template -- over real
// simulated matches, so the exported point log is checked against the engine
// that produced it rather than against a hand-written fixture.
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');

eval(fs.readFileSync(path.join(ROOT, 'simulation/engine.js'), 'utf8')
  + '\nglobalThis.simulateTournament = simulateTournament;');

// Pull exportRows out of the shared match viewer by brace matching, so the test
// always exercises the shipped source and cannot drift from it. It used to live
// inline in the tournament template; both pages now share this one copy.
const tpl = fs.readFileSync(path.join(ROOT, 'simulation/matchview.js'), 'utf8');
const start = tpl.indexOf('function exportRows(m){');
if(start < 0) throw new Error('exportRows not found in simulation/matchview.js');
let depth = 0, end = start;
for(let i = tpl.indexOf('{', start); i < tpl.length; i++){
  if(tpl[i] === '{') depth++;
  else if(tpl[i] === '}' && --depth === 0){ end = i + 1; break; }
}
eval(tpl.slice(start, end) + '\nglobalThis.exportRows = exportRows;');

const pool = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = [];
for(let s = 0; s < Number(process.argv[3] || 8); s++){
  const r = simulateTournament(pool, { seed: 900 + s, playable: null, tour: 'ATP',
                                       surface: 'hard', drawSize: 32,
                                       bestOf: 3, finalSetTiebreak: 7 });
  r.rounds.forEach(rd => rd.matches.forEach(m => {
    if(m.bye) return;
    out.push({ names: m.statNames, rows: exportRows(m),
               // the engine's own view, to check the export against
               truth: m.sets.map(set => set.g.map(g => ({ k: g.k, srv: g.srv, n: g.pts.length }))) });
  }));
}
console.log(JSON.stringify(out));
