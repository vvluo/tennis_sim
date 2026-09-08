/* Tennis engine, ported from simulation/player.py, match.py and tournament.py.
   The page has to simulate on demand, and a static site cannot call Python, so
   the point loop lives here. One seeded generator drives the field, the draw
   and every point, which the Python never did -- there the matches ran off the
   unseeded global `random`, so a --seed reproduced the draw and nothing else. */

// ---- seeded randomness ---------------------------------------------------
function makeRandom(seed){
  let a = seed >>> 0;
  const next = () => {                                   // mulberry32
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  let spare = null;
  return {
    random: next,
    gauss(mu, sd){                                       // Marsaglia polar
      if(spare !== null){ const v = spare; spare = null; return mu + sd * v; }
      let u, v, s;
      do { u = next() * 2 - 1; v = next() * 2 - 1; s = u * u + v * v; }
      while(s >= 1 || s === 0);
      const m = Math.sqrt(-2 * Math.log(s) / s);
      spare = v * m;
      return mu + sd * u * m;
    },
    shuffle(arr){
      for(let i = arr.length - 1; i > 0; i--){
        const j = Math.floor(next() * (i + 1));
        const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
      }
    }
  };
}

// ---- player.py -----------------------------------------------------------
const K = {
  BASE_FIRST_SERVE_PERCENTAGE: 0.55, FIRST_SERVE_GRADIENT: 0.017,
  BASE_DOUBLE_FAULT_RATE: 0.06,      DOUBLE_FAULT_GRADIENT: -0.003,
  FIRST_SERVE_BOOST: 0.14,           SECOND_SERVE_BOOST: 0.0,
  RETURN_GRADIENT: 0.02,             BASE_SERVE_RETURN: 0.78,
  BASE_RALLY_RETURN: 0.78,
  BASE_INCONSISTENCY: 0.14,          INCONSISTENCY_GRADIENT: -0.012,
  RALLY_ADVANTAGE_GRADIENT: 0.01,
  BASE_FORM_SD: 4.0,                 FORM_SD_GRADIENT: -0.3
};
const prob = v => v < 0 ? 0 : v > 1 ? 1 : v;

function drawForm(rng, p){
  if(p.vol === null || p.vol === undefined) return [0, 0, 0, 0];
  const sd = Math.max(K.BASE_FORM_SD + K.FORM_SD_GRADIENT * p.vol, 0);
  if(!sd) return [0, 0, 0, 0];
  return [rng.gauss(0, sd), rng.gauss(0, sd), rng.gauss(0, sd), rng.gauss(0, sd)];
}                                        // [serve, consistency, shot, ret]

function matchup(p, opp, form, oppForm, base){
  const serve = p.srv  + form[0];
  const cons  = p.cons + form[1];
  const shot  = p.shot + form[2];
  const oret  = opp.ret + oppForm[3];
  return {
    firstServePct:   prob(K.BASE_FIRST_SERVE_PERCENTAGE + K.FIRST_SERVE_GRADIENT * serve),
    dfRate:          prob(K.BASE_DOUBLE_FAULT_RATE + K.DOUBLE_FAULT_GRADIENT * cons),
    inconsistency:   prob(K.BASE_INCONSISTENCY + K.INCONSISTENCY_GRADIENT * cons),
    probServeReturn: prob(base.serve + (oret * 0.5 - serve) * K.RETURN_GRADIENT),
    probReturnable:  prob(base.rally + (oret * 0.5 - shot) * K.RALLY_ADVANTAGE_GRADIENT)
  };
}

// ---- scoring strings -----------------------------------------------------
const PT = ['0', '15', '30', '40'];

// Point-record names: one initial plus a surname clipped to SURNAME_LETTERS,
// e.g. "J Pegul". Only the point-by-point uses these -- headers keep full names.
// Mirrors frontend.short_names; the parity test compares the score strings both
// produce, so the two must not drift.
// "J Pegula", or "J Pegul" when surnames are clipped too. The first name grows
// a letter at a time if the two players would otherwise read the same, and
// falls back to the full names if that never separates them.
function shortNames(names, surnameLetters){
  const parts = names.map(n => {
    const i = n.trim().indexOf(' ');
    return i < 0 ? [n.trim(), ''] : [n.slice(0, i), n.slice(i + 1)];
  });
  for(let keep = 1; keep <= 12; keep++){
    const out = parts.map(([f, l]) => {
      if(!l) return f;
      // Clipping takes the LAST word: "Thiago Agustin Tirante" is a Tirante,
      // and cutting the tail off the whole remainder would leave "T Agust".
      const surname = surnameLetters
        ? l.split(' ').pop().slice(0, surnameLetters)
        : l;
      return f.slice(0, keep) + ' ' + surname;
    });
    if(new Set(out).size === out.length) return out;
  }
  return names.slice();
}

function gameScore(sp, rp, names, srv, rcv){
  if(sp >= 4 && sp - rp >= 2) return 'Game ' + names[srv];
  if(rp >= 4 && rp - sp >= 2) return 'Game ' + names[rcv];
  if(sp < 3 || rp < 3)        return PT[sp] + ' - ' + PT[rp];
  if(sp === rp)               return '40 - 40';
  return 'Ad ' + names[sp > rp ? srv : rcv];
}
function tbScore(sp, rp, names, srv, rcv, len){
  const s = names[srv], r = names[rcv];
  if(sp >= len && sp - rp >= 2) return 'Game ' + s;
  if(rp >= len && rp - sp >= 2) return 'Game ' + r;
  return s + ' ' + sp + ' - ' + rp + ' ' + r;
}

// ---- match.py ------------------------------------------------------------
// Side indices: 0 = top of the tie, 1 = bottom. The Python compared Player
// objects; here everything is an index, which is also what the page wants.
function simMatch(rng, top, bottom, names, bestOf, finalSetTiebreak, base){
  // Full names in the record; the panel abbreviates only if it has to.
  const fTop = drawForm(rng, top), fBot = drawForm(rng, bottom);
  const mu = [matchup(top, bottom, fTop, fBot, base), matchup(bottom, top, fBot, fTop, base)];
  const toWin = (bestOf + 1) / 2;
  let server = rng.random() < 0.5 ? 0 : 1;

  function point(firstServe){
    // The shot maker wins by hitting through the opponent OR by the opponent
    // erring, so the inconsistency tested is always the OPPONENT's. (match.py
    // keys this off absolute player identity and gets it backwards whenever
    // p2 serves; this is the corrected rule.)
    const rec = mu[server];
    const boost = firstServe ? K.FIRST_SERVE_BOOST : K.SECOND_SERVE_BOOST;
    const returnRng = rng.random();
    if(returnRng > rec.probServeReturn - boost || rng.random() < mu[1 - server].inconsistency)
      return [server, 1];                                  // unreturned serve
    let maker = 1 - server, shots = 2;
    for(;;){
      const responseRng = rng.random();
      if(responseRng > mu[maker].probReturnable || rng.random() < mu[1 - maker].inconsistency)
        return [maker, shots];
      shots++; maker = 1 - maker;
    }
  }

  function simGame(){
    const m = mu[server], rcv = 1 - server;
    let sp = 0, rp = 0;
    const pts = [];
    for(;;){
      const serveRng = rng.random();
      let winner, shots, first;
      if(serveRng < m.dfRate)                 { winner = rcv; shots = 0; first = false; }
      else if(serveRng > 1 - m.firstServePct) { [winner, shots] = point(true);  first = true; }
      else                                    { [winner, shots] = point(false); first = false; }
      if(winner === server) sp++; else rp++;
      // 4th slot is the first-serve flag: the statistics read it, the page does not.
      pts.push([winner, shots, gameScore(sp, rp, names, server, rcv), first]);
      if(sp >= 4 && sp - rp >= 2) return { k: 'g', srv: server, win: server, pts };
      if(rp >= 4 && rp - sp >= 2) return { k: 'g', srv: server, win: rcv,    pts };
    }
  }

  function simTiebreak(len){
    const first = server;
    let a = 0, b = 0;                                // a = side 0, b = side 1
    const pts = [];
    for(;;){
      const [winner, shots] = point(true);   // as in sim_tiebreak: no serve draw, no DFs
      if(winner === 0) a++; else b++;
      // The scoreline is read from whoever STARTED the tiebreak, not whoever is
      // serving right now -- serve rotates every two points and the score does not.
      const sp = first === 0 ? a : b, rp = first === 0 ? b : a;
      pts.push([winner, shots, tbScore(sp, rp, names, first, 1 - first, len), true]);
      if(a >= len && a - b >= 2) return { k: 't', srv: first, win: 0, pts };
      if(b >= len && b - a >= 2) return { k: 't', srv: first, win: 1, pts };
      if((a + b) % 2 === 1) server = 1 - server;
    }
  }

  function simSet(tbLen){
    let g0 = 0, g1 = 0;
    const games = [];
    for(;;){
      if(g0 === 6 && g1 === 6){
        const startServer = server;
        const tb = simTiebreak(tbLen);
        games.push(tb);
        server = 1 - startServer;                    // serve flips for the next set
        return { win: tb.win, games };
      }
      const g = simGame();
      if(g.win === 0) g0++; else g1++;
      games.push(g);
      server = 1 - server;
      if(g0 >= 6 && g0 - g1 >= 2) return { win: 0, games };
      if(g1 >= 6 && g1 - g0 >= 2) return { win: 1, games };
      if(g0 === 7) return { win: 0, games };
      if(g1 === 7) return { win: 1, games };
    }
  }

  let s0 = 0, s1 = 0;
  const sets = [];
  while(s0 < toWin && s1 < toWin){
    const decider = s0 === toWin - 1 && s1 === toWin - 1;
    const set = simSet(decider ? finalSetTiebreak : 7);
    if(set.win === 0) s0++; else s1++;
    sets.push(set);
  }
  return { winner: s0 >= toWin ? 0 : 1, sets, mu };
}

// ---- frontend.py: scores and statistics ---------------------------------
function setScoreStrings(sets, winner, names){
  // Games score after each game, always read from the match winner's side, so
  // one scoreline reads the same way down the whole match.
  const parts = [];
  sets.forEach(set => {
    let won = 0, lost = 0;
    set.games.forEach(g => {
      if(g.k === 't'){
        const w = g.pts.filter(p => p[0] === g.win).length;
        const l = g.pts.length - w;
        if(g.win === winner){ won = 7; lost = 6; g.sc = '7-6(' + l + ')'; }
        else                { won = 6; lost = 7; g.sc = '6(' + l + ')-7'; }
        return;
      }
      if(g.win === winner) won++; else lost++;
      g.sc = won + '-' + lost;
    });
    set.sc = set.games.length ? set.games[set.games.length - 1].sc : won + '-' + lost;
    parts.push(set.sc);
  });
  // The last point of a set says so; the one that ends the match says that.
  sets.forEach((set, i) => {
    const last = set.games[set.games.length - 1];
    if(!last || !last.pts.length) return;
    const label = i === sets.length - 1 ? 'Game Set Match' : 'Game Set';
    last.pts[last.pts.length - 1][2] = label + ' ' + names[last.win];
  });
  return parts.join(', ');
}

function perSideSetScores(sets){
  return sets.map(set => {
    let top = 0, bottom = 0, entry = null;
    set.games.forEach(g => {
      if(g.k === 't'){
        const w = g.pts.filter(p => p[0] === g.win).length;
        const l = g.pts.length - w;
        if(g.win === 0){ top = 7; bottom = 6; entry = { tbSide: 'bottom', tb: l }; }
        else           { top = 6; bottom = 7; entry = { tbSide: 'top',    tb: l }; }
      } else if(g.win === 0) top++; else bottom++;
    });
    return Object.assign({ top, bottom }, entry || {});
  });
}

function matchStats(sets, names){
  const keys = ['double_faults','first_serves','first_won','second_serves','second_won',
    'serve_points','serve_points_won','serve_games','serve_games_won','return_points_won',
    'points_won','games_won','tiebreaks_won','break_points','break_points_won',
    'unreturned','rally_shots','rallies'];
  const st = {}; keys.forEach(k => st[k] = [0, 0]);
  const ptStreak = [0, 0], gmStreak = [0, 0], bestPt = [0, 0], bestGm = [0, 0];

  sets.forEach(set => set.games.forEach(g => {
    const srv = g.srv, rcv = 1 - srv;
    st.games_won[g.win]++;
    if(g.k === 't') st.tiebreaks_won[g.win]++;
    else { st.serve_games[srv]++; if(g.win === srv) st.serve_games_won[srv]++; }
    for(let s = 0; s < 2; s++){
      gmStreak[s] = s === g.win ? gmStreak[s] + 1 : 0;
      if(gmStreak[s] > bestGm[s]) bestGm[s] = gmStreak[s];
    }
    let sp = 0, rp = 0;
    g.pts.forEach(pt => {
      const w = pt[0], shots = pt[1];
      if(g.k !== 't'){                       // a break point is one the receiver could win the game with
        const needed = rp + 1;
        if(needed >= 4 && needed - sp >= 2){
          st.break_points[rcv]++;
          if(w === rcv) st.break_points_won[rcv]++;
        }
      }
      st.serve_points[srv]++;
      st.points_won[w]++;
      if(w === srv) st.serve_points_won[srv]++; else st.return_points_won[rcv]++;
      if(shots === 0)      st.double_faults[srv]++;
      else if(shots === 1) st.unreturned[srv]++;
      else { st.rally_shots[srv] += shots; st.rallies[srv]++; }
      if(pt[3]){ st.first_serves[srv]++;  if(w === srv) st.first_won[srv]++; }
      else     { st.second_serves[srv]++; if(w === srv) st.second_won[srv]++; }
      for(let s = 0; s < 2; s++){
        ptStreak[s] = s === w ? ptStreak[s] + 1 : 0;
        if(ptStreak[s] > bestPt[s]) bestPt[s] = ptStreak[s];
      }
      if(w === srv) sp++; else rp++;
    });
  }));

  // Python's round() breaks ties to even and Math.round breaks them upward, so
  // a rate landing exactly on .5 printed one point apart between the engines.
  const pyRound = x => {
    const f = Math.floor(x), d = x - f;
    return d > 0.5 ? f + 1 : d < 0.5 ? f : (f % 2 === 0 ? f : f + 1);
  };
  // Python's f'{x:.1f}' breaks ties to even as well, so one decimal needs the
  // same treatment as the percentages.
  const oneDecimal = x => (pyRound(x * 10) / 10).toFixed(1);
  const pct = (n, d, i) => d[i] ? pyRound(100 * n[i] / d[i]) + '%' : '-';
  const ratio = (n, d, i) => d[i] ? n[i] / d[i] : null;
  const rows = [
    ['Double faults',        i => '' + st.double_faults[i],                  i => st.double_faults[i], false],
    ['First serve %',        i => pct(st.first_serves, st.serve_points, i),  i => ratio(st.first_serves, st.serve_points, i), true],
    ['Win % on 1st serve',   i => pct(st.first_won, st.first_serves, i),     i => ratio(st.first_won, st.first_serves, i), true],
    ['Win % on 2nd serve',   i => pct(st.second_won, st.second_serves, i),   i => ratio(st.second_won, st.second_serves, i), true],
    ['Break points',         i => st.break_points_won[i] + '/' + st.break_points[i], i => st.break_points_won[i], true],
    ['Unreturned serves',    i => '' + st.unreturned[i],                     i => st.unreturned[i], true],
    ['Avg rally length',     i => st.rallies[i] ? oneDecimal(st.rally_shots[i] / st.rallies[i]) : '-',
                             i => ratio(st.rally_shots, st.rallies, i), true],
    ['Service points won',   i => '' + st.serve_points_won[i],               i => st.serve_points_won[i], true],
    ['Service games won',    i => st.serve_games_won[i] + '/' + st.serve_games[i], i => st.serve_games_won[i], true],
    ['Receiving points won', i => '' + st.return_points_won[i],              i => st.return_points_won[i], true],
    ['Points won',           i => '' + st.points_won[i],                     i => st.points_won[i], true],
    ['Games won',            i => '' + st.games_won[i],                      i => st.games_won[i], true],
    ['Max points in a row',  i => '' + bestPt[i],                            i => bestPt[i], true],
    ['Max games in a row',   i => '' + bestGm[i],                            i => bestGm[i], true],
    ['Tiebreaks won',        i => '' + st.tiebreaks_won[i],                  i => st.tiebreaks_won[i], true]
  ];
  return rows.map(([label, show, value, higherBetter]) => {
    const a = value(0), b = value(1);
    let better = null;
    if(a !== null && b !== null && a !== b) better = (a > b) === higherBetter ? 'a' : 'b';
    return { label, a: show(0), b: show(1), better };
  });
}

// ---- tournament.py -------------------------------------------------------
// ---- draw shape -----------------------------------------------------------
// Any draw from 2 to 256. For N players the bracket is the next power of two,
// a quarter of the bracket is seeded, and the empty slots are byes handed to the
// top seeds. Checked against 116 real ATP/WTA events: seeds is bracket/4 on
// every one of them, and byes is 2^b - c for N = 2^b + c.
const MAX_DRAW = 256;
const QUALIFIER_SHARE = 1 / 8;          // 16 of 128, as the slam did
const MIN_QUALIFYING_DRAW = 16;         // smaller than this, everyone is a direct entrant

function bracketFor(draw){
  let p = 1;
  while(p < draw) p *= 2;
  return p;
}
// A quarter of the bracket is seeded -- 8 in a 32, 16 in a 64, 32 in a 128,
// checked against 116 real ATP/WTA events. Two rules bend that:
//
//   * Byes are a seeding privilege, so there can never be more byes than seeds.
//     A draw below three quarters of its bracket needs more byes than a quarter
//     of the bracket provides, and the seed count rises to the next power of two
//     that covers them. Every real draw size -- 28, 30, 32, 48, 56, 64, 96, 128
//     -- already satisfies this and is untouched.
//   * Below four seeds a draw is not meaningfully seeded and gets none. That
//     applies only to draws of eight or fewer, where any bye simply goes to the
//     best-ranked player without calling anyone a seed.
const MIN_SEEDS = 4;
function seedsFor(draw){
  const bracket = bracketFor(draw);
  const needed = Math.max(bracket / 4, bracket - draw);   // a quarter, or enough for the byes
  if(needed < MIN_SEEDS) return 0;
  let seeds = 1;
  while(seeds < needed) seeds *= 2;                       // keep the 4/8/16/32 progression
  return Math.min(seeds, bracket / 2);
}

// Round names run R256 ... R16, then the three everyone names instead.
function roundNames(bracket){
  const out = [];
  for(let size = bracket; size >= 2; size /= 2){
    out.push(size === 2 ? 'F' : size === 4 ? 'SF' : size === 8 ? 'QF' : 'R' + size);
  }
  return out;
}
// "1R", "2R", ... for the early rounds; the last three keep their own names.
function exitLabels(names){
  const out = {};
  names.forEach((n, i) => { out[n] = /^R/.test(n) ? (i + 1) + 'R' : n; });
  return out;
}

function buildField(candidates, rng, playable, drawSize, dropout = 0.10, qualifyingDropout = 0.60){
  // Below 16 a draw is too small to run a qualifying event worth modelling.
  const QUALIFIERS = drawSize < MIN_QUALIFYING_DRAW ? 0 : Math.round(drawSize * QUALIFIER_SHARE);
  const DIRECT_ENTRANTS = drawSize - QUALIFIERS;
  const ranked = candidates.slice().sort((a, b) => a.rank - b.rank);
  const accepted = [];
  let index = 0;
  for(index = 0; index < ranked.length; index++){
    if(accepted.length === DIRECT_ENTRANTS) break;
    if(rng.random() >= dropout) accepted.push(ranked[index]);
  }
  // Qualifying draws only from players direct entry never reached: someone who
  // declined a main-draw place has withdrawn, not gone to play qualifying.
  const qualifiers = [];
  for(let i = index; i < ranked.length && qualifiers.length < QUALIFIERS; i++){
    if(rng.random() >= qualifyingDropout) qualifiers.push(ranked[i]);
  }
  const ent = (e, q, pl) => ({ name: e.name, rank: e.rank, ratings: e.ratings,
                               qualifier: !!q, playable: !!pl, seed: null });
  const field = accepted.map(e => ent(e)).concat(qualifiers.map(e => ent(e, true)));
  if(field.length !== drawSize) throw new Error('field is ' + field.length + ', need ' + drawSize);

  if(playable){
    const inField = field.find(e => e.name === playable);
    if(inField) inField.playable = true;
    else {
      const custom = candidates.find(c => c.name === playable);
      if(!custom) throw new Error(playable + ' is not among the candidates');
      // Someone ranked below the last direct entrant did not earn a main-draw
      // place, so they come in the way anyone else that far down would: through
      // qualifying. Anyone above that line simply took a place they had earned.
      const lastDirect = accepted[accepted.length - 1];
      const viaQualifying = !!lastDirect && custom.rank > lastDirect.rank;
      field[field.length - 1] = ent(custom, viaQualifying, true);
    }
  }
  field.slice().sort((a, b) => a.rank - b.rank).slice(0, seedsFor(drawSize))
       .forEach((e, i) => e.seed = i + 1);
  return field;
}

function seedingOrder(sections){
  let order = [0];
  while(order.length < sections){
    const size = order.length * 2;
    const next = [];
    order.forEach(p => { next.push(p); next.push(size - 1 - p); });
    order = next;
  }
  return order;
}

function seedSections(rng, sections){
  const order = seedingOrder(sections);
  const tiers = [[0, 1], [1, 2]];
  let lo = 2;
  while(lo < sections){ tiers.push([lo, Math.min(lo * 2, sections)]); lo *= 2; }
  const assignment = {};
  tiers.forEach(([a, b]) => {
    const drawn = order.slice(a, b);
    rng.shuffle(drawn);
    drawn.forEach((section, offset) => assignment[a + offset + 1] = section);
  });
  return assignment;
}

function buildDraw(field, rng, drawSize){
  const bracket = bracketFor(drawSize);
  const seeds = seedsFor(drawSize);
  const sectionSize = seeds ? bracket / seeds : bracket;
  const byes = bracket - drawSize;

  const slots = new Array(bracket).fill(null);
  const sections = seeds ? seedSections(rng, seeds) : {};
  const seeded = {};
  field.forEach(e => { if(e.seed) seeded[e.seed] = e; });

  const seatOf = {};
  Object.keys(sections).forEach(seed => {
    const seat = sections[seed] * sectionSize;
    seatOf[seed] = seat;
    slots[seat] = seeded[seed] || null;
  });

  // Byes go to the top seeds, one each: the seed's first-round opponent seat is
  // left empty, which is exactly how a 48 draw puts 16 seeds straight into R32.
  const empty = new Set();
  const seedSeats = new Set(Object.values(seatOf));
  let placed = 0;
  for(let seed = 1; seed <= seeds && placed < byes; seed++){
    const seat = seatOf[seed];
    if(seat === undefined) continue;
    empty.add(seat ^ 1);
    placed++;
  }

  // A small draw can need more byes than it has seeds -- nine players in a
  // sixteen bracket need seven -- and the surplus goes on down the ranking
  // rather than at random, because a bye is a reward for standing and byes are
  // handed out best-ranked first.
  const rest = field.filter(e => !e.seed).sort((a, b) => a.rank - b.rank);
  const surplus = Math.max(0, byes - placed);
  const byeGetters = rest.slice(0, surplus);
  const others = rest.slice(surplus);
  rng.shuffle(others);

  if(surplus){
    const pairs = [];
    for(let i = 0; i < bracket; i += 2){
      if(!empty.has(i) && !empty.has(i + 1) && !seedSeats.has(i) && !seedSeats.has(i + 1)){
        pairs.push(i);
      }
    }
    rng.shuffle(pairs);                       // which pair is still drawn
    byeGetters.forEach((entrant, k) => {
      const i = pairs[k];
      if(i === undefined) return;
      const seat = rng.random() < 0.5 ? i : i + 1;
      slots[seat] = entrant;
      empty.add(seat ^ 1);
    });
  }

  let r = 0;
  for(let i = 0; i < bracket; i++){
    if(slots[i] !== null || empty.has(i)) continue;
    slots[i] = others[r++] || null;
  }
  return slots;
}

// How much of the observed rating spread is skill rather than measurement noise.
// A rating is an estimate and estimates overshoot, so the spread is pulled in by
// the reliability of the estimate. Fitted against a year of real results: ATP
// mean absolute error across bins of published OVR gap falls 0.047 -> 0.020 at
// 0.8; the WTA already fits at 1.0. The difference is data volume -- 5 tour
// matches for the median ATP player against 18 for the WTA.
const SHRINK = { ATP: 0.8, WTA: 1.0 };

// Two baselines, one per job. BASE_SERVE_RETURN sets how often the serve comes
// back, so it governs the share of points that end in one shot; BASE_RALLY_RETURN
// sets how often a rally ball comes back, so it governs how long rallies run.
// They were a single constant, which made those two quantities impossible to fit
// at once. Solved per tour against a year of rally lengths, then offset per
// surface -- globally, not per player.
const TOUR_BASE = { ATP: { serve: 0.8986, rally: 0.8502 }, WTA: { serve: 0.94, rally: 0.8601 } };
const SURFACE_OFFSET = {
  ATP: { hard: { serve: -0.0191, rally: -0.0033 }, grass: { serve: -0.0743, rally: -0.0420 }, clay: { serve: +0.0589, rally: +0.0226 } },
  WTA: { hard: { serve: -0.0046, rally: +0.0000 }, grass: { serve: -0.0222, rally: -0.0270 }, clay: { serve: +0.0466, rally: +0.0215 } },
};
function basesFor(tour, surface){
  const b = TOUR_BASE[tour] || TOUR_BASE.ATP;
  const o = (SURFACE_OFFSET[tour] || {})[surface || 'hard'] || { serve: 0, rally: 0 };
  return { serve: b.serve + o.serve, rally: b.rally + o.rally };
}

function toPlayer(entrant, shift, shrink){
  const t = entrant.ratings;
  const attr = v => 5.0 + shrink * (v + shift - 5.0);
  // vol is left unshrunk: it measures dispersion, not skill.
  return { name: entrant.name, srv: attr(t.SRV), cons: attr(t.CONS),
           ret: attr(t.RET), shot: attr(t.SHOT), vol: t.CONS + shift };
}

function runTournament(draw, rng, bestOf, finalSetTiebreak, shrink, base){
  // The published ratings are min-max scaled so their mean is not 5, but every
  // constant above is calibrated so 5.0 gives tour-average rates. Re-centre the
  // field without touching the spread between players.
  const entrants = draw.filter(Boolean);
  const mean = entrants.reduce((acc, e) =>
    acc + (e.ratings.SRV + e.ratings.RET + e.ratings.SHOT + e.ratings.CONS) / 4, 0) / entrants.length;
  const shift = 5.0 - mean;
  entrants.forEach(e => e.player = toPlayer(e, shift, shrink));

  const names = roundNames(draw.length);
  const labels = exitLabels(names);
  const rounds = [];
  let alive = draw.slice();
  names.forEach(name => {
    const matches = [], winners = [];
    for(let i = 0; i < alive.length; i += 2){
      const top = alive[i], bottom = alive[i + 1];
      // An empty seat is a bye: the other player advances without playing, and
      // the tie is still recorded so the bracket shows them sitting the round out.
      if(!top || !bottom){
        const through = top || bottom;
        if(through){
          matches.push({ top: through ? side(through, true) : null,
                         bottom: null, bye: true, score: 'bye',
                         setScores: [], sets: [], stats: [], statNames: [through.name, ''],
                         round: name, winner: through, loser: null });
          winners.push(through);
        }
        continue;
      }
      const pair = [top.name, bottom.name];
      const played = simMatch(rng, top.player, bottom.player, pair, bestOf, finalSetTiebreak, base);
      const wonByTop = played.winner === 0;
      const winner = wonByTop ? top : bottom, loser = wonByTop ? bottom : top;
      matches.push({
        top: side(top, wonByTop), bottom: side(bottom, !wonByTop),
        score: setScoreStrings(played.sets, played.winner, pair),
        setScores: perSideSetScores(played.sets),
        sets: played.sets.map(s => ({
          win: s.win, sc: s.sc,
          g: s.games.map(g => ({ k: g.k, srv: g.srv, win: g.win, sc: g.sc,
                                 pts: g.pts.map(p => [p[0], p[1], p[2]]) }))
        })),
        stats: matchStats(played.sets, pair), statNames: pair,
        round: name, winner, loser
      });
      winners.push(winner);
    }
    rounds.push({ name, matches });
    alive = winners;
  });

  const champion = alive[0];
  const playable = entrants.find(e => e.playable) || null;
  let playableResult = null;
  if(playable){
    if(playable === champion) playableResult = 'Win';
    else {
      for(const r of rounds){
        const m = r.matches.find(m => m.loser === playable);
        if(m){ playableResult = labels[r.name]; break; }
      }
    }
  }
  rounds.forEach(r => r.matches.forEach(m => { delete m.winner; delete m.loser; delete m.round; }));
  return { rounds, champion: champion.name, championSeed: champion.seed,
           playable: playable ? playable.name : null, playableResult };
}

function side(e, won){
  return { name: e.name, seed: e.seed, q: e.qualifier, playable: e.playable, won };
}

function simulateTournament(pool, opts){
  const drawSize = Math.max(2, Math.min(MAX_DRAW, opts.drawSize || 128));
  if(pool.length < drawSize) throw new Error('pool holds ' + pool.length + ', need ' + drawSize);
  const rng = makeRandom(opts.seed);
  const field = buildField(pool, rng, opts.playable, drawSize);
  const draw = buildDraw(field, rng, drawSize);
  const bestOf = opts.bestOf, tb = opts.finalSetTiebreak || 10;
  const out = runTournament(draw, rng, bestOf, tb, SHRINK[opts.tour] ?? 1.0,
                            basesFor(opts.tour, opts.surface));
  out.tour = opts.tour;
  out.bestOf = bestOf;
  out.drawSize = drawSize;
  out.bracket = bracketFor(drawSize);
  out.seeds = seedsFor(drawSize);
  out.byes = out.bracket - drawSize;
  return out;
}
