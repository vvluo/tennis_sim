// Drives the closed-form forecaster and the point-by-point engine over the same
// matchups and reports both win rates, so the Python test can compare them.
const fs = require('fs');
const path = require('path');
const R = path.resolve(__dirname, '..', 'simulation') + '/';
eval(fs.readFileSync(R + 'engine.js', 'utf8') + '\n'
   + fs.readFileSync(R + 'forecast.js', 'utf8').replace(/if\(typeof module[\s\S]*$/, ''));

const N = Number(process.argv[2] || 4000);
const rng = makeRandom(Number(process.argv[3] || 20260908));
const out = [];
for(const tour of ['ATP', 'WTA']){
  for(const surface of ['hard', 'clay', 'grass']){
    const base = basesFor(tour, surface);
    for(let k = 0; k < 4; k++){
      const a = () => 3 + rng.random() * 5;
      // vol null => drawForm returns zeros, so the parameters are fixed and the
      // exact probability can be compared without a form integral in the way.
      const A = {name:'A', srv:a(), ret:a(), shot:a(), cons:a(), vol:null};
      const B = {name:'B', srv:a(), ret:a(), shot:a(), cons:a(), vol:null};
      const bestOf = k % 2 ? 3 : 5, fst = k < 2 ? 7 : 10;
      let wins = 0;
      for(let i = 0; i < N; i++)
        if(simMatch(rng, A, B, ['A','B'], bestOf, fst, base).winner === 0) wins++;
      const z = [0,0,0,0];
      const exact = 0.5 * winProbForForm(A, B, z, z, bestOf, fst, base, 0)
                  + 0.5 * winProbForForm(A, B, z, z, bestOf, fst, base, 1);
      out.push({tour, surface, bestOf, finalSetTiebreak: fst, n: N,
                simulated: wins / N, exact});
    }
  }
}

// --- tiebreaks, bucketed by who opened them -------------------------------
// Averaging over the random opening server cancels any error in the serve
// ROTATION, so the match-level comparison above cannot see one. Points are
// i.i.d. here (vol=null, no form noise), so a tiebreak's outcome given its
// opening server is independent of how the set reached 6-6 -- which makes the
// engine's own tiebreaks a clean, non-circular check on the rotation.
const tb = [];
for(const len of [7, 10]){
  const rng2 = makeRandom(4242 + len);
  const base = basesFor('ATP', 'hard');
  const a = () => 4 + rng2.random() * 3;
  const A = {name:'A', srv:a(), ret:a(), shot:a(), cons:a(), vol:null};
  const B = {name:'B', srv:a(), ret:a(), shot:a(), cons:a(), vol:null};
  const mu = [matchup(A, B, [0,0,0,0], [0,0,0,0], base),
              matchup(B, A, [0,0,0,0], [0,0,0,0], base)];
  const pS = [servePointProb(mu, 0), servePointProb(mu, 1)];
  const seen = [{w:0, n:0}, {w:0, n:0}];          // indexed by opening server
  for(let i = 0; i < 40000; i++){
    const r = simMatch(rng2, A, B, ['A','B'], 3, len, base);
    r.sets.forEach(set => set.games.forEach(g => {
      if(g.k !== 't') return;
      // Only the DECIDING set uses finalSetTiebreak; every other set uses 7.
      // In a best-of-3 the last set is the decider only when it is the third.
      const decider = r.sets.length === 3 && set === r.sets[2];
      if((len === 10) !== decider) return;
      seen[g.srv].n++;
      if(g.win === 0) seen[g.srv].w++;
    }));
  }
  for(let first = 0; first < 2; first++)
    if(seen[first].n > 200)
      tb.push({len, first, n: seen[first].n, simulated: seen[first].w / seen[first].n,
               exact: tiebreakProb(pS, len, first)});
}

// --- exact symmetry: a correct rotation makes the opener irrelevant --------
// Under the standard 1-2-2-2 rotation each side has served equally after every
// even number of points, and the win-by-two tail is symmetric, so who serves
// first does not change the tiebreak win probability AT ALL. A phase error in
// the rotation breaks this antisymmetrically (~0.05), which makes this a far
// sharper probe than any sampled comparison.
let symWorst = 0;
{
  const r = makeRandom(99);
  for(let i = 0; i < 20000; i++){
    const pS = [r.random(), r.random()], len = [5, 7, 10, 12][i % 4];
    symWorst = Math.max(symWorst, Math.abs(tiebreakProb(pS, len, 0) - tiebreakProb(pS, len, 1)));
  }
}

// --- who serves the first game of the NEXT set ----------------------------
// simSet flips from whoever STARTED the tiebreak, so a set decided in a
// tiebreak hands serve differently from one decided on games. setDist has to
// reproduce that or the sets after it are served by the wrong player.
const carry = [];
{
  const rng3 = makeRandom(777);
  const base = basesFor('ATP', 'hard');
  const a = () => 4 + rng3.random() * 3;
  const A = {name:'A', srv:a(), ret:a(), shot:a(), cons:a(), vol:null};
  const B = {name:'B', srv:a(), ret:a(), shot:a(), cons:a(), vol:null};
  const mu = [matchup(A, B, [0,0,0,0], [0,0,0,0], base),
              matchup(B, A, [0,0,0,0], [0,0,0,0], base)];
  const pS = [servePointProb(mu, 0), servePointProb(mu, 1)];
  const gS = [gameProb(pS[0]), gameProb(pS[1])];
  // ONLY the opening set of each match. Aggregating over every consecutive
  // pair instead conditions on "a further set was played", and whether the
  // match continued depends on who won -- which setDist couples to the next
  // server. In a best-of-5 a second set is always played, so this is unbiased.
  const seen = [[0, 0, 0, 0], [0, 0, 0, 0]];   // [openingServer][winner*2+nextServer]
  for(let i = 0; i < 30000; i++){
    const r = simMatch(rng3, A, B, ['A','B'], 5, 7, base);
    const first = r.sets[0].games[0].srv;
    seen[first][r.sets[0].win * 2 + r.sets[1].games[0].srv]++;
  }
  for(let first = 0; first < 2; first++){
    const n = seen[first].reduce((a, b) => a + b, 0);
    if(n < 500) continue;
    const d = setDist(pS, gS, 7, first);
    carry.push({first, n, simulated: seen[first].map(v => v / n), exact: d});
  }
}
console.log(JSON.stringify({matches: out, tiebreaks: tb, symmetry: symWorst, carry}));
