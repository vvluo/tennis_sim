// Runs whole seasons through the shipped page's own script, so the tests
// exercise what is served rather than a re-implementation.
const fs = require('fs');
const path = require('path');
const PAGE = path.resolve(__dirname, '..', process.argv[2] || 'season.html');
const page = fs.readFileSync(PAGE, 'utf8');
// The last BARE <script> block, and the first </script> that closes it.
// Two things sit either side of it: the shared "About this site" panel brings
// its own <script> earlier in the document, so anchoring on the first one
// spliced the two together; and the footer's Buy Me a Coffee tag closes a
// <script> AFTER it, so taking the last </script> swallowed the closing tag and
// the file stopped parsing at "Unexpected token '<'".
const open = page.lastIndexOf('<script>') + 8;
const js = page.slice(open, page.indexOf('</script>', open));
if(!js.includes('simulateTournament'))
  throw new Error('extracted the wrong <script> block from the page');

// minimal DOM so the page's wiring can run headless
const stub = () => ({
  style: { setProperty(){}, getPropertyValue: () => '' },
  classList: { add(){}, remove(){}, toggle(){}, contains: () => false },
  dataset: {}, addEventListener(){}, setAttribute(){}, getAttribute: () => null,
  querySelector: () => null, querySelectorAll: () => [],
  set innerHTML(v){}, set textContent(v){},
});
globalThis.document = {
  getElementById: stub, createElement: stub,
  addEventListener(){},                      // the sheet binds Escape here
  documentElement: { style: { setProperty(){} },
                     getAttribute: () => null, setAttribute(){} },
  querySelector: () => null, querySelectorAll: () => [],
};
globalThis.localStorage = { getItem: () => null, setItem(){} };
// The shared match viewer asks once at load whether the artifact `downloads`
// capability is available; headless there is no window at all.
globalThis.window = globalThis;
eval(js + '\nglobalThis.__ = {state, runEvent, allocateWeek, CALS, POOLS, POINTS, ENTRY, entryChance, restChance, TAIL_DAYS, ensureFields, cal, pointsFor, roundNames, bracketFor, qualifiersFor, buildDraw, seedsFor, taperFor, directEntrants, seasonDrop, rankingBreakdown, SLOTS, QUALIFYING_DROPOUT, atHome, runFinals, finalsField, FINALS_POINTS, FINALS_FIELD, eventPayout, seasonCurve, seasonElapsed, residualAt, residualAt, snapshotRank, rankAt, rankIn, slotOf, committedTo, COMMITTED_RANK, WTA_SLOTTED_1000, ATP_OPTIONAL_1000, DATA, residualTable};');

// Every name is read through this namespace: binding any of them locally would
// collide with the declarations the evaluated page script puts in this scope.
const P = globalThis.__;
const out = { tours: {} };

// Play a whole season the way the page does: allocate each week's entry lists
// together, then play that week's events.
function season(tour, who, seed){
  const S = P.state;
  S.tour = tour; S.playable = who;
  // hurt and absence were missing here, so every injury leaked into the next
  // simulated season: by the third one most of the pool was carrying an injury
  // that never happened in it.
  S.table = new Map(); S.busy = new Map(); S.hurt = new Map();
  S.absence = new Map(); S.load = new Map();
  // rankViews is per-season too: left behind, a deadline early in the next
  // season answers with a snapshot from the last one. Same class of bug as the
  // injuries that used to leak between seasons here.
  S.rankViews = new Map();
  S.loadWeek = null; S.seed = seed; S.rested = 0;
  const list0 = P.CALS[tour].filter(e => !e.skip);
  list0.forEach(e => { delete e.thin; });
  const list = P.CALS[tour].filter(e => !e.skip);
  // The finals have no draw and no weekly allocation; running them through
  // runEvent would quietly play them as an ordinary eight-player bracket.
  const finals = list.filter(e => e.format === 'rr');
  const byWeek = new Map();
  list.filter(e => e.format !== 'rr').forEach(ev => {
    const w = ev.sweek;
    if(!byWeek.has(w)) byWeek.set(w, []);
    byWeek.get(w).push(ev);
  });
  const entries = new Map(), fieldOf = new Map(), res = { pbp: 0, injuries: 0, injuryWeeks: 0,
                                     entered: 0, events: list.length };
  [...byWeek.keys()].sort((a, b) => a - b).forEach(w => {
    const evs = byWeek.get(w);
    const fields = P.allocateWeek(evs, makeRandom((seed ^ (w * 2654435761)) >>> 0), S, who);
    evs.forEach((ev, k) => {
      fieldOf.set(ev, fields[k]);
      fields[k].forEach(e => {
        if(!entries.has(e.name)) entries.set(e.name, []);
        const span = [ev.sday, ev.sday_end]; span.ev = ev;
        entries.get(e.name).push(span);
      });
      const r = P.runEvent(ev, makeRandom(4321 + w * 7919 + k), who, fields[k]);
      res.pbp += r.yourMatches.length;
      res.wo = (res.wo || 0) + r.yourMatches.filter(m => m.walkover).length;
      res.eventWalkovers = (res.eventWalkovers || 0) + (r.walkovers || []).length;
      res.injuries += r.injured.length;
      r.injured.forEach(i => res.injuryWeeks += i.weeks);
      if(r.yourEntry) res.entered++;
      else if(who){
        res.absence = res.absence || {};
        res.absence[r.yourResult] = (res.absence[r.yourResult] || 0) + 1;
        if(ev.level === 'Grand Slam') res.missedSlams = (res.missedSlams || 0) + 1;
        else if(/1000$/.test(ev.level)) res.missed1000 = (res.missed1000 || 0) + 1;
      }
    });
  });
  finals.forEach((ev, k) => {
    const f = P.finalsField(ev, S, who);
    fieldOf.set(ev, f);
    f.forEach(e => {
      if(!entries.has(e.name)) entries.set(e.name, []);
      const span = [ev.sday, ev.sday_end]; span.ev = ev;
      entries.get(e.name).push(span);
    });
    const r = P.runFinals(ev, makeRandom(4321 + k * 7919), who, f);
    res.pbp += r.yourMatches.length;
    res.wo = (res.wo || 0) + r.yourMatches.filter(m => m.walkover).length;
    res.eventWalkovers = (res.eventWalkovers || 0) + (r.walkovers || []).length;
    res.injuries += r.injured.length;
    r.injured.forEach(i => res.injuryWeeks += i.weeks);
    // yourEntry, not the reason string: matching on the wording counted a
    // player as having entered the moment the wording changed.
    if(r.yourEntry) res.entered++;
    else if(who){
      res.absence = res.absence || {};
      res.absence[r.yourResult] = (res.absence[r.yourResult] || 0) + 1;
    }
    res.finals = { field: f.map(e => ({ name: e.name, seed: e.seed,
                                        points: e.points, rank: e.rank })),
                   groups: r.groups, closing: r.closing, champion: r.champion,
                   gained: f.map(e => S.table.get(e.name).points - e.points) };
  });
  let clashes = 0, total = 0;
  for(const l of entries.values()){
    l.sort((a, b) => a[0] - b[0]); total += l.length;
    for(let i = 1; i < l.length; i++)
      if(l[i][0] < l[i - 1][1] - P.TAIL_DAYS) clashes++;
  }
  const rows = [...S.table.values()];
  const thin = list.filter(e => e.thin).length;
  const band = (a, b) => {
    const v = P.POOLS[tour].slice(a, b).map(x => (entries.get(x.name) || []).length);
    return v.reduce((x, y) => x + y, 0) / v.length;
  };
  // Do concurrent events of the SAME level end up with comparable fields?
  // Measured from the allocated field itself -- deriving it from start dates is
  // wrong, because two events in one week need not start on the same day.
  let twinGap = 0;
  for(const g of byWeek.values()){
    if(g.length < 2) continue;
    // `lrank` -- the standing at the entry deadline -- and not `rank`, which is
    // where the player finished LAST season. The allocator picks on the former,
    // so measuring the latter asks whether two fields are comparable by a
    // yardstick nothing in the allocation ever used.
    const med = ev => {
      const r = (fieldOf.get(ev) || []).map(e => e.lrank ?? e.rank).sort((a, b) => a - b);
      return r.length ? r[Math.floor(r.length / 2)] : 0;
    };
    for(let i = 0; i < g.length; i++)
      for(let j = i + 1; j < g.length; j++)
        if(g[i].level === g[j].level) twinGap = Math.max(twinGap, Math.abs(med(g[i]) - med(g[j])));
  }
  // Entries by band counting ONLY players who were never hurt that season. The
  // targets for a schedule are stated for a fit player, and an all-players mean
  // is dragged down by whoever spent nine weeks out.
  const fitBand = (a, b) => {
    const v = P.POOLS[tour].slice(a, b).filter(x => !S.hurt.has(x.name))
                .map(x => (entries.get(x.name) || []).length);
    return v.length ? v.reduce((x, y) => x + y, 0) / v.length : 0;
  };
  const you = S.table.get(who);
  const entriesOf = new Map();
  for(const [name, spans] of entries) entriesOf.set(name, spans.map(x => x.ev).filter(Boolean));
  return {
    entriesOf, hurt: S.hurt,
    fitBands: { top10: fitBand(0, 10), r11_30: fitBand(10, 30), r31_60: fitBand(30, 60),
                r61_120: fitBand(60, 120), r121_250: fitBand(120, 250) },
    ...res, clashes, entries: total, twinGap, thin, rested: S.rested,
    wins: rows.reduce((a, r) => a + r.w, 0), losses: rows.reduce((a, r) => a + r.l, 0),
    titles: rows.reduce((a, r) => a + r.titles, 0),
    bands: { top10: band(0, 10), r11_30: band(10, 30), r31_60: band(30, 60),
             r61_120: band(60, 120), r121_250: band(120, 250) },
    you: { name: who, record: you ? [you.w, you.l] : [0, 0], points: you ? you.points : 0 },
    // The whole ranking record for the top of the table, so the counting rules
    // can be recomputed independently rather than taken on trust.
    ranking: rows.sort((a, b) => b.points - a.points).slice(0, 40).map(r => ({
      name: r.name, points: r.points, titles: r.titles,
      counted: [...P.rankingBreakdown(r, tour).counted].map(g => g.event),
      results: r.results.map(g => ({ event: g.event, level: g.level, pts: g.pts,
                                     round: g.round, slot: g.slot,
                                     qualifier: !!g.qualifier })),
    })),
  };
}

// Allocating a week that holds nothing playable, which the run loop avoids by
// only allocating inside `if(!ev.skip)` -- so nothing else would catch it.
let emptyWeekOk = true;
try { P.allocateWeek([], makeRandom(1), P.state, ''); } catch(e){ emptyWeekOk = false; }
let skippedEnsureOk = true;
try {
  P.state.tour = 'ATP'; P.state.fields = new Map(); P.state.busy = new Map();
  P.state.load = new Map(); P.state.loadWeek = null;
  const list = P.CALS.ATP;
  list.forEach((ev, i) => { if(ev.skip) P.ensureFields(i); });
} catch(e){ skippedEnsureOk = false; }

// Points actually CREDITED at a 56-draw Masters, run on its own so the totals
// are attributable. Checking the table's shape in the source cannot see whether
// the right row is used; this can.
function openingRoundPoints(tour, drawWanted, level){
  const S = P.state;
  S.tour = tour; S.playable = ''; S.table = new Map(); S.busy = new Map(); S.rankViews = new Map();
  S.load = new Map(); S.loadWeek = null; S.rested = 0; S.seed = 4242;
  const ev = P.CALS[tour].find(e => !e.skip && e.draw === drawWanted && e.level === level);
  if(!ev) return null;
  const fields = P.allocateWeek([ev], makeRandom(11), S, '');
  const before = new Map([...S.table].map(([k, v]) => [k, v.points]));
  const res = P.runEvent(ev, makeRandom(99), '', fields[0]);
  // whoever lost the FIRST round played gets that round's points and no more
  const first = P.roundNames(P.bracketFor(ev.draw))[0];
  const losers = [...S.table].filter(([n, v]) =>
    (v.points - (before.get(n) || 0)) > 0 && v.w === 0);
  const pts = losers.length ? Math.min(...losers.map(([n, v]) => v.points - (before.get(n) || 0))) : null;
  return { event: ev.name, draw: ev.draw, level: ev.level, firstRound: first, points: pts };
}
// Home advantage, participation only: below 1000 level a player from the host
// country should be markedly over-represented in the field relative to their
// share of the pool, and at the compulsory levels not at all.
function homeAdvantage(tour){
  const S = P.state;
  const bands = { below1000: [], mandatory: [] };
  let neutralAtHome = 0;
  for(const ev of P.CALS[tour]){
    if(ev.skip) continue;
    const avail = P.POOLS[tour].filter(x => x.country && x.country === ev.country).length;
    if(avail < 8) continue;
    let home = 0, tot = 0;
    for(let t = 0; t < 20; t++){
      S.tour = tour; S.table = new Map(); S.busy = new Map(); S.rankViews = new Map();
      S.load = new Map(); S.loadWeek = null; S.rested = 0;
      const f = P.allocateWeek([ev], makeRandom(1500 + t), S, '')[0];
      f.forEach(x => {
        tot++;
        if(P.atHome(x, ev)) home++;
        if(!x.country && x.country === ev.country) neutralAtHome++;
      });
    }
    const lift = (100 * home / tot) / (100 * avail / P.POOLS[tour].length);
    const key = (ev.level === 'Grand Slam' || /1000$/.test(ev.level))
      ? 'mandatory' : 'below1000';
    bands[key].push({ name: ev.name, lift });
  }
  const mean = a => a.length ? a.reduce((x, y) => x + y.lift, 0) / a.length : null;
  // Measured on the function, not on the draws: at the compulsory levels the
  // base chance is already ~0.96, so an odds boost moves it by a single point
  // and would be invisible in a field. Only the curve itself shows the guard.
  const curve = {};
  for(const [lv, rank] of [['ATP 250', 60], ['ATP 500', 60], ['WTA 250', 60],
                           ['ATP 1000', 60], ['Grand Slam', 60]])
    curve[lv] = { away: P.entryChance(lv, rank, 0, false),
                  home: P.entryChance(lv, rank, 0, true) };
  return { curve, below1000: mean(bands.below1000), mandatory: mean(bands.mandatory),
           belowCount: bands.below1000.length, mandatoryCount: bands.mandatory.length,
           best: bands.below1000.sort((a, b) => b.lift - a.lift).slice(0, 3),
           neutralAtHome };
}

// The DRAW itself: seeds spread geometrically, byes to the top seeds, the rest
// shuffled. The season page calls the engine's buildDraw, the same one the
// grand-slam page uses, so this checks that path end to end.
function drawStructure(tour, name){
  const S = P.state;
  S.tour = tour; S.table = new Map(); S.busy = new Map(); S.rankViews = new Map();
  S.load = new Map(); S.loadWeek = null; S.rested = 0;
  const ev = P.CALS[tour].find(e => e.name === name && !e.skip);
  if(!ev) return null;
  const bracket = P.bracketFor(ev.draw), seeds = P.seedsFor(ev.draw);
  const byes = bracket - ev.draw;
  let halves = 0, quarters = 0, byesToSeeds = 0, qRank = [], dRank = [], trials = 60;
  for(let t = 0; t < trials; t++){
    S.busy = new Map();
    const field = P.allocateWeek([ev], makeRandom(3000 + t), S, '')[0];
    field.forEach(e => (e.qualifier ? qRank : dRank).push(e.rank));
    const slots = P.buildDraw(field, makeRandom(9000 + t), ev.draw);
    const seat = {};
    slots.forEach((e, i) => { if(e && e.seed) seat[e.seed] = i; });
    if(seeds >= 2 && (seat[1] < bracket/2) !== (seat[2] < bracket/2)) halves++;
    if(seeds >= 4){
      const q = n => Math.floor(seat[n] / (bracket/4));
      if(new Set([q(1),q(2),q(3),q(4)]).size === 4) quarters++;
    }
    if(byes > 0){
      let n = 0;
      for(let k = 1; k <= Math.min(seeds, byes); k++)
        if(seat[k] !== undefined && slots[seat[k] ^ 1] === null) n++;
      if(n === Math.min(seeds, byes)) byesToSeeds++;
    }
  }
  const med = a => { a = a.slice().sort((x,y)=>x-y); return a.length ? a[Math.floor(a.length/2)] : null; };
  // How far the qualifiers are SPREAD, per draw. Without the qualifying dropout
  // they are simply the next names below the cutoff, so they arrive as a
  // contiguous block roughly as wide as their own number; the dropout scatters
  // them across two or three times that range.
  const spans = [];
  for(let t = 0; t < trials; t++){
    S.busy = new Map();
    const f = P.allocateWeek([ev], makeRandom(7000 + t), S, '')[0];
    const r = f.filter(e => e.qualifier).map(e => e.rank).sort((a,b)=>a-b);
    if(r.length > 1) spans.push((r[r.length-1] - r[0]) / r.length);
  }
  const spread = spans.length ? spans.reduce((a,b)=>a+b,0)/spans.length : null;
  return { name, draw: ev.draw, bracket, seeds, byes, trials,
           halves, quarters, byesToSeeds, qualifierSpread: spread,
           medianDirectRank: med(dRank), medianQualifierRank: med(qRank) };
}

// Qualifier counts per event, to hold against the tours' published breakdowns.
const qualifierCounts = {};
for(const t of ['ATP', 'WTA']){
  qualifierCounts[t] = {};
  for(const e of P.CALS[t]) if(!e.skip && e.draw)
    qualifierCounts[t][e.name] = { draw: e.draw, level: e.level,
                                   q: P.qualifiersFor(t, e.draw, e.name) };
}

// The player you PICK must not be handed a main draw their ranking could never
// reach. The mandatory-entry shortcut used to force the picked player into every
// grand slam and 1000 regardless of rank, which put ranks in the 400s into Indian
// Wells. Measured as mandatory main draws entered per season, by rank band.
function mandatoryEntries(tour, rank){
  const S = P.state;
  const me = P.POOLS[tour].find(p => p.rank >= rank);
  if(!me) return null;
  const weeks = new Map();
  for(const ev of P.CALS[tour]){
    if(!weeks.has(ev.sweek)) weeks.set(ev.sweek, []);
    weeks.get(ev.sweek).push(ev);
  }
  let slam = 0, m1000 = 0, seasons = 4;
  for(let t = 0; t < seasons; t++){
    S.tour = tour; S.table = new Map(); S.busy = new Map(); S.rankViews = new Map();
    S.load = new Map(); S.loadWeek = null; S.rested = 0;
    let wi = 0;
    for(const [, evs] of [...weeks].sort((a, b) => a[0] - b[0])){
      const fields = P.allocateWeek(evs, makeRandom(6100 + t * 331 + wi * 13), S, me.name);
      wi++;
      fields.forEach((f, i) => {
        if(!f.some(x => x.name === me.name)) return;
        if(evs[i].level === 'Grand Slam') slam++;
        else if(/1000$/.test(evs[i].level)) m1000++;
      });
    }
  }
  return { rank: me.rank, slams: slam / seasons, masters: m1000 / seasons };
}

// Every scoreline in the "your matches" panel must read from YOUR player's
// side. The engine's setScoreStrings orients from the MATCH WINNER, which is
// right for the neutral "winner d. loser" panel on the grand-slam page but put a
// 6-4 6-3 next to the words "lost to" here. Checked against the recorded set
// winners, which are draw-side indices and carry no orientation of their own.
function scoreOrientation(tour){
  const S = P.state;
  const who = P.POOLS[tour][3].name;
  const ev = P.CALS[tour].find(e => e.level === 'Grand Slam');
  let checked = 0, wrong = 0, losses = 0;
  for(let t = 0; t < 30; t++){
    S.tour = tour; S.table = new Map(); S.busy = new Map(); S.rankViews = new Map();
    S.load = new Map(); S.loadWeek = null; S.rested = 0;
    const f = P.allocateWeek([ev], makeRandom(700 + t * 57), S, who)[0];
    if(!f.some(x => x.name === who)) continue;
    const res = P.runEvent(ev, makeRandom(900 + t * 31), who, f);
    res.yourMatches.forEach(m => {
      const mine = m.statNames[0] === who ? 0 : 1;
      if(!m.won) losses++;
      m.score.split(',').forEach((part, i) => {
        const set = m.sets[i];
        if(!set) return;
        const [a, b] = part.trim().split('-').map(x => Number(x.replace(/\(.*/, '')));
        checked++;
        if((set.win === mine) !== (a > b)) wrong++;
      });
    });
  }
  return { checked, wrong, losses };
}

// A mandatory draw must never reach past its acceptance list, even when it
// CANNOT otherwise fill. Measured on a deliberately depleted week -- everyone in
// the top 250 already committed elsewhere -- because in an ordinary week direct
// entry and qualifying exhaust themselves well above the cut, so the ceiling is
// never loaded and a probe on a normal week proves nothing. A short field is the
// correct outcome here; a full one means the bottom of the pool was called up.
function acceptanceCeiling(tour){
  const S = P.state;
  const out = [];
  const targets = [
    P.CALS[tour].find(e => e.level === 'Grand Slam'),
    P.CALS[tour].find(e => /1000$/.test(e.level) && e.draw >= 96),
  ].filter(Boolean);
  for(const ev of targets){
    S.tour = tour; S.table = new Map(); S.load = new Map(); S.rankViews = new Map();
    S.loadWeek = null; S.rested = 0;
    S.busy = new Map(P.POOLS[tour].filter(p => p.rank <= 250).map(p => [p.name, 1e9]));
    const f = P.allocateWeek([ev], makeRandom(4242), S, '');
    const field = f[0] || [];
    out.push({ level: ev.level, draw: ev.draw, size: field.length,
               worst: field.length ? Math.max(...field.map(x => x.rank)) : 0 });
  }
  return out;
}

// The tour finals, measured over several seasons. Everything here is checked
// against the season the run actually played, not against the seed rankings.
function finalsRuns(tour, n){
  const runs = [];
  for(let t = 0; t < n; t++){
    const r = season(tour, '', 3300 + t * 617);
    if(r.finals) runs.push(r.finals);
  }
  return runs;
}

// An injured qualifier loses their place and the next player down takes it.
// Built directly rather than measured off a season, because an injury landing on
// one of the top eight in the finals week is rare enough that a handful of
// seasons would usually show none, and the test would pass without ever
// exercising the replacement.
function finalsInjuryReplacement(tour){
  const S = P.state;
  const ev = P.CALS[tour].find(e => e.format === 'rr');
  if(!ev) return null;
  S.tour = tour; S.busy = new Map(); S.load = new Map(); S.loadWeek = null;
  // a made-up standings table: the pool's first twelve, on descending points
  const top = P.POOLS[tour].slice(0, 12);
  S.table = new Map(top.map((p, i) => [p.name,
    { name: p.name, points: 5000 - i * 100, titles: 0, w: 0, l: 0 }]));
  const healthy = P.finalsField(ev, S, '').map(e => e.name);
  // now hurt the second and fifth qualifiers past the start of the week
  const hurt = [healthy[1], healthy[4]];
  S.busy = new Map(hurt.map(n => [n, ev.sday + 30]));
  const after = P.finalsField(ev, S, '').map(e => e.name);
  return { healthy, hurt, after,
           standings: top.map(p => p.name).slice(0, 12) };
}

// What carried load does to a COMPULSORY entry. Majors and 1000s are the events
// nobody skips to freshen up, so a heavy season must barely move the chance of
// entering one -- while it moves an optional 250 a lot.
function wearCurve(tour){
  const loads = [0, 5, 10, 20, 40];
  const far = P.taperFor({ toMajor: 9 }), near = P.taperFor({ toMajor: 1 });
  const at = (level, rank, taper) =>
    loads.map(l => P.entryChance(level, rank, l, false, taper));
  return { loads, slam: at('Grand Slam', 5, far), m1000: at(tour + ' 1000', 5, far),
           optional: at(tour + ' 250', 150, far),
           optionalNear: at(tour + ' 250', 150, near) };
}
const taperShape = () => ({
  far: P.taperFor({ toMajor: 9 }), week1: P.taperFor({ toMajor: 1 }),
  week2: P.taperFor({ toMajor: 2 }), week3: P.taperFor({ toMajor: 3 }),
});

// Why the player you picked is absent, by ranking. The reasons have to differ:
// a world 400 is not managing a workload, and the world number one is not
// missing Indian Wells because he failed to qualify.
function absenceByRank(tour, rank, n){
  const me = P.POOLS[tour].find(p => p.rank >= rank);
  if(!me) return null;
  const reasons = {};
  let entered = 0, slams = 0, m1000 = 0;
  for(let t = 0; t < n; t++){
    const r = season(tour, me.name, 31000 + t * 4517);
    entered += r.entered;
    for(const [k, v] of Object.entries(r.absence || {})) reasons[k] = (reasons[k] || 0) + v;
    slams += r.missedSlams || 0; m1000 += r.missed1000 || 0;
  }
  return { rank: me.rank, name: me.name, seasons: n, entered, reasons,
           missedSlams: slams, missed1000: m1000 };
}

// The ATP's top-30 commitment: every major and every Masters bar Monte Carlo,
// plus four 500s of which one falls after the US Open. Injury is the only
// excuse, so anyone the season hurt is left out of the count.
function commitment(tour, n){
  const cal = P.CALS[tour].filter(e => !e.skip);
  const us = cal.find(e => e.name === 'US Open');
  const majors = cal.filter(e => e.level === 'Grand Slam').length;
  const mand = cal.filter(e => /1000$/.test(e.level) && e.name !== 'Monte Carlo').length;
  let people = 0, slams = 0, masters = 0, monte = 0, fives = 0, ruleOk = 0;
  for(let t = 0; t < n; t++){
    const r = season(tour, '', 70000 + t * 613);
    P.POOLS[tour].slice(0, 30).forEach(p => {
      if(r.hurt.has(p.name)) return;
      people++;
      const evs = r.entriesOf.get(p.name) || [];
      slams += evs.filter(e => e.level === 'Grand Slam').length;
      masters += evs.filter(e => /1000$/.test(e.level) && e.name !== 'Monte Carlo').length;
      monte += evs.filter(e => e.name === 'Monte Carlo').length;
      const f = evs.filter(e => /500$/.test(e.level));
      fives += f.length;
      if(f.length >= 4 && us && f.some(e => e.sday > us.sday)) ruleOk++;
    });
  }
  return { people, majors, mand,
           slamShare: slams / people / majors, mastersShare: masters / people / mand,
           monteShare: monte / people, fives: fives / people, ruleShare: ruleOk / people };
}

// WTA mandatory-1000 dropout among players whose ranking gets them direct entry
// and who are not injured. Driven by matches played this season, not by carried
// load: the load barely moves between May and October while the season total
// more than doubles.
function thousandDropout(tour, n){
  const want = tour === 'WTA'
    ? ['Indian Wells', 'Miami', 'Madrid', 'Rome', 'Toronto', 'Cincinnati', 'Beijing']
    : ['Indian Wells', 'Miami', 'Madrid', 'Rome', 'Montreal', 'Cincinnati',
       'Shanghai', 'Paris'];
  const acc = {}; want.forEach(w => acc[w] = { elig: 0, played: 0 });
  const S = P.state;
  for(let t = 0; t < n; t++){
    S.tour = tour; S.playable = '';
    S.table = new Map(); S.busy = new Map(); S.hurt = new Map(); S.rankViews = new Map();
    S.absence = new Map(); S.load = new Map(); S.loadWeek = null; S.rested = 0;
    const list = P.CALS[tour], fields = new Map();
    list.forEach((ev, i) => {
      if(ev.skip) return;
      if(!fields.has(i)){
        if(ev.format === 'rr') fields.set(i, P.finalsField(ev, S, ''));
        else {
          const g = [];
          list.forEach((e, j) => { if(!e.skip && e.format !== 'rr' && e.sweek === ev.sweek) g.push(j); });
          const b = P.allocateWeek(g.map(j => list[j]),
            makeRandom((50000 + t * 977) ^ (ev.sweek * 2654435761)), S, '');
          g.forEach((j, k) => fields.set(j, b[k]));
        }
      }
      if(want.indexOf(ev.name) >= 0){
        const direct = P.directEntrants(ev.draw, tour, ev.name).direct;
        const inField = new Set((fields.get(i) || []).map(x => x.name));
        P.POOLS[tour].forEach(p => {
          if(p.rank > direct) return;
          if((S.hurt.get(p.name) ?? -Infinity) > ev.sday) return;
          acc[ev.name].elig++;
          if(inField.has(p.name)) acc[ev.name].played++;
        });
      }
      const rng = makeRandom((50000 + t * 977) + i * 7919);
      if(ev.format === 'rr') P.runFinals(ev, rng, '', fields.get(i) || []);
      else P.runEvent(ev, rng, '', fields.get(i) || []);
    });
  }
  const out = {};
  want.forEach(w => out[w] = acc[w].elig ? 1 - acc[w].played / acc[w].elig : null);
  return out;
}

// The crowded-calendar term, measured on the curve itself rather than through a
// season: a back-to-back Masters must carry more than its date alone gives it,
// and the difference is small enough that a sampled season cannot see it.
// Participation by level for the top 30, gated on the same eligibility bar at
// every level so the levels can be compared with each other.
function byLevel(tour, n){
  const acc = {};
  const S = P.state;
  for(let t = 0; t < n; t++){
    S.tour = tour; S.playable = '';
    S.table = new Map(); S.busy = new Map(); S.hurt = new Map(); S.rankViews = new Map();
    S.absence = new Map(); S.load = new Map(); S.loadWeek = null; S.rested = 0;
    const list = P.CALS[tour], fields = new Map();
    list.forEach((ev, i) => {
      if(ev.skip || ev.format === 'rr') return;
      if(!fields.has(i)){
        const g = [];
        list.forEach((e, j) => { if(!e.skip && e.format !== 'rr' && e.sweek === ev.sweek) g.push(j); });
        const b = P.allocateWeek(g.map(j => list[j]),
          makeRandom((8800 + t * 977) ^ (ev.sweek * 2654435761)), S, '');
        g.forEach((j, k) => fields.set(j, b[k]));
      }
      const lv = ev.level;
      if(!acc[lv]) acc[lv] = { elig: 0, played: 0 };
      const direct = P.directEntrants(ev.draw, tour, ev.name).direct;
      const inField = new Set((fields.get(i) || []).map(x => x.name));
      P.POOLS[tour].slice(0, 30).forEach(p => {
        if(p.rank > direct) return;
        if((S.hurt.get(p.name) ?? -Infinity) > ev.sday) return;
        acc[lv].elig++;
        if(inField.has(p.name)) acc[lv].played++;
      });
      P.runEvent(ev, makeRandom((8800 + t * 977) + i * 7919), '', fields.get(i) || []);
    });
  }
  const out = {};
  Object.keys(acc).forEach(lv => out[lv] = acc[lv].played / acc[lv].elig);
  return out;
}

const crowding = (() => {
  const at = (m, crowded) => P.seasonDrop('ATP 1000', m, { crowded });
  return { m30: { crowded: at(30, true), alone: at(30, false) },
           m45: { crowded: at(45, true), alone: at(45, false) } };
})();

const home = { ATP: homeAdvantage('ATP'), WTA: homeAdvantage('WTA') };

const draws = ['Australian Open','Indian Wells','Monte Carlo','Halle']
  .map(n => drawStructure('ATP', n)).filter(Boolean);

const openingRound = {
  atp56: openingRoundPoints('ATP', 56, 'ATP 1000'),
  atp96: openingRoundPoints('ATP', 96, 'ATP 1000'),
};

for(const tour of ['ATP', 'WTA']){
  const cal = P.CALS[tour];
  const nobody = season(tour, '', 2026);
  // A picked player's season is sampled across seeds, not taken from one. About
  // 7% of injuries end a season outright, so a single sample says "14 matches"
  // roughly one year in fifteen -- and no assertion on one sample can tell that
  // apart from the entry model collapsing, which is what it is there to catch.
  // Alcaraz's fifteen seasons here run 13, 41, 48 ... 76 around a median of 63.
  // Entries per band are averaged across seasons rather than taken from one.
  // A single season swings by a full event and a half either way -- ATP 11-30
  // runs 21.3 to 22.8 across twelve seeds -- so a tuned bound asserted on one
  // sample is hostage to which seed happens to be written here.
  const spread = [];
  for(let t = 0; t < 6; t++) spread.push(season(tour, '', 3300 + t * 617));
  const meanOf = key => {
    const out = {};
    for(const k of Object.keys(spread[0][key]))
      out[k] = spread.reduce((a, r) => a + r[key][k], 0) / spread.length;
    return out;
  };
  const fitBandsMean = meanOf('fitBands'), bandsMean = meanOf('bands');

  const picked = [];
  for(let t = 0; t < 9; t++) picked.push(season(tour, P.POOLS[tour][2].name, 2026 + t * 911));
  const byMatches = picked.slice().sort((a, b) =>
    (a.you.record[0] + a.you.record[1]) - (b.you.record[0] + b.you.record[1]));
  const someone = byMatches[Math.floor(byMatches.length / 2)];
  out.tours[tour] = {
    emptyWeekOk, skippedEnsureOk,
    openingRound, draws, home: home[tour], qualifyingDropout: P.QUALIFYING_DROPOUT,
    qualifierCounts: qualifierCounts[tour],
    finals: finalsRuns(tour, 6),
    commitment: commitment(tour, 8),
    thousandDropout: thousandDropout(tour, 10),
    crowding,
    byLevel: byLevel(tour, 8),
    wear: wearCurve(tour),
    absence: [1, 400].map(r => absenceByRank(tour, r, 6)).filter(Boolean),
    taper: taperShape(),
    slots: P.SLOTS[tour],
    finalsInjury: finalsInjuryReplacement(tour),
    finalsPoints: P.FINALS_POINTS, finalsField: P.FINALS_FIELD,
    calendar: P.CALS[tour].map(e => ({ name: e.name, level: e.level,
                    format: e.format || null, skip: e.skip || null })),
    acceptanceCeiling: acceptanceCeiling(tour),
    scoreOrientation: scoreOrientation(tour),
    mandatory: [1, 40, 150, 300, 420].map(r => mandatoryEntries(tour, r)).filter(Boolean),
    events: cal.length, simulated: cal.filter(e => !e.skip).length,
    skipped: cal.filter(e => e.skip).length,
    ranking: nobody.ranking,
    fitBands: fitBandsMean,
    wins: nobody.wins, losses: nobody.losses, titles: nobody.titles,
    champions: cal.filter(e => !e.skip).length,
    pointByPointWithNobodySelected: nobody.pbp,
    clashes: nobody.clashes, entries: nobody.entries, twinGap: nobody.twinGap,
    injuries: nobody.injuries, thin: nobody.thin, rested: nobody.rested,
    entryTop10At250: P.entryChance(tour + ' 250', 1, 0),
    entryTop10At500: P.entryChance(tour + ' 500', 1, 0),
    entryCurve250: [1, 30, 60, 120, 250].map(r => P.entryChance(tour + ' 250', r, 0)),
    entryCurve500: [1, 30, 60, 120, 250].map(r => P.entryChance(tour + ' 500', r, 0)),
    restMajorWeek: P.restChance(0, 0), restSmallWeek: P.restChance(2, 0),
    injuryWeeks: nobody.injuries ? nobody.injuryWeeks / nobody.injuries : 0,
    bands: bandsMean,
    entersTop10: bandsMean.top10, entersRank21to40: bandsMean.r31_60,
    levels: [...new Set(cal.map(e => e.level))],
    pointsTables: Object.keys(P.POINTS[tour]),
    you: { ...someone.you, entered: someone.entered, matches: someone.pbp,
           walkovers: someone.wo || 0 },
    walkovers: nobody.eventWalkovers || 0,
  };
}
// Control for the clash test: allocate every event on its own with an empty
// commitment ledger, which is what the page did before weeks were allocated as
// a unit. If this does NOT produce clashes, the detector is broken and the
// zero above means nothing.
function clashesUnscheduled(tour, seed){
  const S = P.state;
  S.tour = tour; S.playable = ''; S.table = new Map(); S.rankViews = new Map();
  S.load = new Map(); S.loadWeek = null; S.rested = 0;
  const list = P.CALS[tour].filter(e => !e.skip);
  const entries = new Map();
  list.forEach((ev, i) => {
    S.busy = new Map();                       // nobody is ever committed
    const f = P.allocateWeek([ev], makeRandom((seed ^ (i * 2654435761)) >>> 0), S, '');
    f[0].forEach(e => {
      if(!entries.has(e.name)) entries.set(e.name, []);
      entries.get(e.name).push([ev.sday, ev.sday_end]);
    });
  });
  let clashes = 0;
  for(const l of entries.values()){
    l.sort((a, b) => a[0] - b[0]);
    for(let i = 1; i < l.length; i++)
      if(l[i][0] < l[i - 1][1] - P.TAIL_DAYS) clashes++;
  }
  return clashes;
}
for(const tour of ['ATP', 'WTA'])
  out.tours[tour].clashesWithoutLedger = clashesUnscheduled(tour, 2026);


// ---- the live ranking ------------------------------------------------------
// The payout curve is the one thing here that must be EXACT: it is what the
// real-points decay is measured against, and an error in it silently rescales
// every player's residual. Checked against what a played season actually
// credits, which is how the version that paid the champion F instead of W was
// found -- it was 13.5% low, and no other test noticed.
for(const tour of ['ATP', 'WTA']){
  const S = P.state;
  S.tour = tour; S.playable = null;
  S.table = new Map(); S.busy = new Map(); S.hurt = new Map(); S.rankViews = new Map();
  S.absence = new Map(); S.load = new Map(); S.rankViews = new Map();
  S.loadWeek = null; S.seed = 4242; S.rested = 0;
  const list = P.CALS[tour].filter(e => !e.skip && e.level !== 'Next Gen Finals');
  list.forEach(e => { delete e.thin; });
  const byWeek = new Map();
  list.filter(e => e.format !== 'rr').forEach(ev => {
    if(!byWeek.has(ev.sweek)) byWeek.set(ev.sweek, []);
    byWeek.get(ev.sweek).push(ev);
  });
  const weeks = [...byWeek.keys()].sort((a, b) => a - b);

  // the view in the very first week, before anything has been played, must
  // reproduce the ranking the pool arrived with -- ranking onto dense positions
  // 1..N instead promoted every WTA player sitting past a gap in the pool
  P.snapshotRank(weeks[0]);
  const v0 = P.rankAt(weeks[0]);
  let identical = 0;
  for(const pl of P.POOLS[tour]) if(P.rankIn(v0, pl) === pl.rank) identical++;

  for(const w of weeks){
    const evs = byWeek.get(w);
    const f = P.allocateWeek(evs, makeRandom((4242 ^ (w * 2654435761)) >>> 0), S, null);
    evs.forEach((ev, k) => P.runEvent(ev, makeRandom(4321 + w * 7919 + k), null, f[k]));
  }
  list.filter(e => e.format === 'rr').forEach((ev, k) =>
    P.runFinals(ev, makeRandom(4321 + k * 7919), null, P.finalsField(ev, S, null)));

  const credited = new Map();
  for(const r of S.table.values())
    for(const g of r.results) credited.set(g.event, (credited.get(g.event) || 0) + g.pts);
  let worst = 0, worstEv = null, analytic = 0, paid = 0;
  for(const ev of list){
    const a = P.eventPayout(tour, ev), c = credited.get(ev.name) || 0;
    analytic += a; paid += c;
    if(Math.abs(a - c) > worst){ worst = Math.abs(a - c); worstEv = ev.name; }
  }
  // how far the live ranking drifts from the one the pool arrived with
  const vEnd = P.rankAt(weeks[weeks.length - 1]);
  let drift = 0, driftTop = 0, nTop = 0;
  for(const pl of P.POOLS[tour]){
    const d = Math.abs(P.rankIn(vEnd, pl) - pl.rank);
    drift += d;
    if(pl.rank <= 100){ driftTop += d; nTop++; }
  }

  // WTA: a compulsory 1000 owns a slot only for players automatically eligible.
  // ATP: it owns one regardless of where they stand now.
  const slotted = tour === 'ATP'
    ? ev => /1000$/.test(ev.level) && !P.ATP_OPTIONAL_1000.has(ev.name)
    : ev => /1000$/.test(ev.level) && P.WTA_SLOTTED_1000.has(ev.name);
  const ev1000 = list.find(slotted);
  const split = { auto: P.slotOf(tour, ev1000, false, true),
                  notAuto: P.slotOf(tour, ev1000, false, false) };

  out.tours[tour].live = {
    seasonPayout: P.seasonCurve(tour).total,
    analytic, paid, worst, worstEv,
    elapsedAtStart: P.seasonElapsed(tour, weeks[0]),
    elapsedAtEnd: P.seasonElapsed(tour, 999),
    week0Identical: identical, poolSize: P.POOLS[tour].length,
    meanDrift: drift / P.POOLS[tour].length,
    meanDriftTop100: nTop ? driftTop / nTop : 0,
    // Measured on a major far enough into the year that its deadline does not
    // clamp at week zero: the Australian Open is in week 2, so six weeks out
    // lands before the season starts and reports a lead of two.
    slamLead: (() => { const e = P.CALS[tour].find(x => x.level === 'Grand Slam'
                                                    && x.sweek >= 6);
                       return e.sweek - e.deadWeek; })(),
    otherLead: (() => { const e = P.CALS[tour].find(x =>
                          x.level !== 'Grand Slam' && !x.skip && x.format !== 'rr'
                          && x.sweek >= 6);
                        return e ? e.sweek - e.deadWeek : null; })(),
    slotSplit: split,
    // exported so the Python copy of this table can be held against it
    pointsTable: Object.fromEntries(Object.entries(P.POINTS[tour] || {})
      .map(([lv, rows]) => [tour + '|' + lv, rows])),
    tiers: (() => {
      // Where this tour's real points sit across the three tiers, and whether a
      // tier-1 chunk actually leaves in the week we play that tournament -- the
      // defending property, which is the whole reason tier 1 exists.
      const drops = (P.DATA.drops || {})[tour] || {};
      let ev = 0, wk = 0, sub = 0, rest = 0;
      for(const d of Object.values(drops)){
        for(const [, pts] of d.ev) ev += pts;
        for(const [, pts] of d.wk) wk += pts;
        for(const [, pts] of (d.sub || [])) sub += pts;
        rest += d.rest;
      }
      // The biggest single tier-1 holding on this tour, and what happens to it.
      let who = null, best = 0, at = null;
      for(const [name, d] of Object.entries(drops))
        for(const [evName, pts] of d.ev){
          const c = P.CALS[tour].find(x => x.name === evName);
          if(c && pts > best){ best = pts; who = name; at = c; }
        }
      const pl = who && (P.POOLS[tour] || []).find(x => x.name === who);
      const before = pl ? P.residualAt(tour, pl, at.sweek) : 0;
      const after = pl ? P.residualAt(tour, pl, at.sweek + 1) : 0;
      // Crossing a week also advances the smooth tier-3 decay, so the fall is
      // the tier-1 chunk PLUS that week's share of whatever is decaying. Without
      // this the check was out by the proxy's step -- 1.3 points for Sinner.
      const d3 = drops[who] ? drops[who].rest : 0;
      const fade = P.seasonElapsed(tour, at.sweek + 1) - P.seasonElapsed(tour, at.sweek);
      const expected = best + d3 * fade;
      return { ev, wk, sub, rest, who, best, expected, event: at && at.name, week: at && at.sweek,
               before, after, dropped: before - after,
               week0: pl ? P.residualAt(tour, pl, 0) : 0,
               real: pl ? pl.points : 0 };
    })(),
  };
}

// The ATP commitment is granted on last season's finish, so it must NOT read the
// live view: a top-30 player who slides still owes the Masters. Asserted on the
// function itself -- driving it through a season cannot separate "released from
// the commitment" from "skipped it for wear".
{
  const S = P.state;
  S.tour = 'ATP'; S.table = new Map(); S.rankViews = new Map();
  // A major, not a Masters: committedTo returns false for every 1000 because
  // Masters attendance is modelled as a wear gradient rather than a hard rule.
  const major = P.CALS.ATP.find(e => e.level === 'Grand Slam');
  const inside = P.POOLS.ATP.find(p => p.rank === P.COMMITTED_RANK);
  const outside = P.POOLS.ATP.find(p => p.rank === P.COMMITTED_RANK + 1);
  // a snapshot that says the opposite of the static ranking
  S.rankViews.set(0, new Map([[inside.name, 400], [outside.name, 1]]));
  out.tours.ATP.commitIgnoresLiveRank = {
    insideStillOwes: P.committedTo('ATP', inside, major),
    outsideStillFree: !P.committedTo('ATP', outside, major),
  };
}

console.log(JSON.stringify(out));
