/* Closed-form match forecasting.

   Playing a 128 draw point by point is 127 matches x ~150 points, and all but
   the handful involving the player you picked are thrown away as soon as a
   winner falls out. This computes the winner directly instead.

   Points in the engine are i.i.d. GIVEN the server and the drawn form, so a
   matchup collapses to two numbers: the probability each player wins a point on
   their own serve. Everything above that -- game, tiebreak, set, match -- is
   exact arithmetic on those two numbers, no sampling.

   Form is the one genuinely random input, and it is drawn ONCE per match. So
   drawing the form exactly as simMatch does, computing the win probability it
   implies, and flipping a single coin is distributionally IDENTICAL to playing
   the points out -- not an approximation of it. tests/test_forecast_parity.py
   holds the two to the same win rates.

   Depends on engine.js for K, prob, matchup and drawForm. */

// ---- one point -----------------------------------------------------------
// P(server wins a point), given both sides' matchup parameters.
function servePointProb(mu, server){
  const s = mu[server], r = mu[1 - server];
  const incS = s.inconsistency, incR = r.inconsistency;

  // Rally, once the serve comes back. The receiver hits first (maker = 1-server
  // in point()), and a maker wins when their own shot beats probReturnable OR
  // the OPPONENT errs -- so the inconsistency in each term is the other side's.
  const A = (1 - r.probReturnable) + r.probReturnable * incS;  // receiver ends it
  const B = (1 - s.probReturnable) + s.probReturnable * incR;  // server ends it
  const cont = (1 - A) * (1 - B);
  // receiver fails to end it, then server does, summed over rally lengths
  const rallyToServer = cont >= 1 ? 0.5 : (1 - A) * B / (1 - cont);

  // A serve is unreturned when returnRng clears the threshold or the receiver
  // errs; otherwise the rally above decides it.
  const onServe = boost => {
    const t = Math.min(1, Math.max(0, s.probServeReturn - boost));
    return (1 - t) + t * incR + t * (1 - incR) * rallyToServer;
  };

  // simGame's branch order: double fault first, then first serve, then second.
  const fsp = s.firstServePct, df = s.dfRate;
  const pFirst = Math.max(0, 1 - Math.max(1 - fsp, df));
  const pSecond = Math.max(0, 1 - df - pFirst);
  return pFirst * onServe(K.FIRST_SERVE_BOOST) + pSecond * onServe(K.SECOND_SERVE_BOOST);
}

// ---- one game ------------------------------------------------------------
// P(server holds), from p = P(server wins a point). Deuce is a geometric tail.
function gameProb(p){
  const q = 1 - p;
  const deuce = (p * p + q * q) <= 0 ? 0.5 : p * p / (p * p + q * q);
  return p*p*p*p * (1 + 4*q + 10*q*q) + 20 * p*p*p * q*q*q * deuce;
}

// ---- one tiebreak --------------------------------------------------------
// P(side 0 wins a tiebreak of `len`, with `first` serving the opening point).
// Serve changes after point 1 and every two points after it.
// Scratch buffers, reused across calls. These run once per simulated match, so
// allocating a memo table per call dominated the cost.
const MAX_TB = 30;
const TB_SCRATCH = new Float64Array((MAX_TB + 2) * (MAX_TB + 2));
const SET_SCRATCH = new Float64Array(7 * 7 * 2 * 4);

function tiebreakProb(pS, len, first){
  if(!(len >= 1 && len <= MAX_TB))
    throw new RangeError('tiebreak length ' + len + ' is outside 1..' + MAX_TB);
  const serverAt = t => first ^ (((t + 1) >> 1) & 1);   // t = points already played
  // From len-1 all square the pair of points is one serve each, and a split
  // returns to the same position with the roles swapped -- which leaves the
  // odds unchanged, so the tail is a single ratio rather than a recursion.
  const P = serverAt(2 * (len - 1)), Q = 1 - P;
  const w = pS[P] * (1 - pS[Q]);            // P takes both
  const l = (1 - pS[P]) * pS[Q];            // Q takes both
  const tail = (w + l) <= 0 ? 0.5 : w / (w + l);
  const allSquare = P === 0 ? tail : 1 - tail;

  // Filled backwards, so every state reads cells already written this call.
  // The grid runs one past `len` on each side purely so those reads land on
  // written terminal cells; states beyond the win-by-two tail are unreachable
  // because (len-1, len-1) short-circuits to `allSquare`.
  const W = len + 2, m = TB_SCRATCH;
  for(let a = len + 1; a >= 0; a--){
    for(let b = len + 1; b >= 0; b--){
      const i = a * W + b;
      if(a >= len && a - b >= 2){ m[i] = 1; continue; }
      if(b >= len && b - a >= 2){ m[i] = 0; continue; }
      if(a >= len - 1 && b >= len - 1){ m[i] = allSquare; continue; }
      const srv = serverAt(a + b);
      const p0 = srv === 0 ? pS[0] : 1 - pS[1];   // P(side 0 takes this point)
      m[i] = p0 * m[i + W] + (1 - p0) * m[i + 1];
    }
  }
  return m[0];
}

// ---- one set -------------------------------------------------------------
// Joint distribution over (winner, who serves the next game), because the
// server carries across sets and the number of games played is random.
// Returns [p(0 wins, next srv 0), p(0,1), p(1 wins, next 0), p(1,1)].
function setDist(pS, gS, tbLen, first){
  // Filled backwards over (games, games, server) -- 98 states -- into one flat
  // buffer. The first version walked forward accumulating path weights, which
  // is exponential in games played and made forecasting slower than playing the
  // points out; the second allocated a 4-vector per state, which then dominated
  // what was left. This allocates nothing.
  const tb = [tiebreakProb(pS, tbLen, 0), tiebreakProb(pS, tbLen, 1)];
  const d = SET_SCRATCH;
  const at = (g0, g1, srv) => (((g0 * 7) + g1) * 2 + srv) * 4;
  for(let t = 12; t >= 0; t--){
    for(let g0 = Math.min(6, t); g0 >= 0; g0--){
      const g1 = t - g0;
      if(g1 < 0 || g1 > 6) continue;
      for(let srv = 0; srv < 2; srv++){
        const o = at(g0, g1, srv), next = 1 - srv;
        d[o] = d[o + 1] = d[o + 2] = d[o + 3] = 0;
        if(g0 === 6 && g1 === 6){
          // simSet flips from whoever STARTED the tiebreak, not the last server
          const p0 = tb[srv];
          d[o + next] = p0;
          d[o + 2 + next] = 1 - p0;
          continue;
        }
        const hold = gS[srv];
        for(let k = 0; k < 2; k++){
          const srvWon = k === 0, w = srvWon ? hold : 1 - hold;
          if(w <= 0) continue;
          const side = srvWon ? srv : next;              // who took the game
          const n0 = g0 + (side === 0 ? 1 : 0), n1 = g1 + (side === 1 ? 1 : 0);
          if((n0 >= 6 && n0 - n1 >= 2) || n0 === 7){ d[o + next] += w; continue; }
          if((n1 >= 6 && n1 - n0 >= 2) || n1 === 7){ d[o + 2 + next] += w; continue; }
          const q = at(n0, n1, next);
          d[o]     += w * d[q];
          d[o + 1] += w * d[q + 1];
          d[o + 2] += w * d[q + 2];
          d[o + 3] += w * d[q + 3];
        }
      }
    }
  }
  const o = at(0, 0, first);
  return [d[o], d[o + 1], d[o + 2], d[o + 3]];
}

// ---- one match -----------------------------------------------------------
// P(side 0 wins), given the two per-serve point probabilities.
function matchProbFromPoints(pS, bestOf, finalSetTiebreak, firstServer){
  const gS = [gameProb(pS[0]), gameProb(pS[1])];
  const toWin = (bestOf + 1) / 2;
  const cacheN = new Map(), cacheD = new Map();
  const dist = (tbLen, first) => {
    const c = tbLen === finalSetTiebreak ? cacheD : cacheN;
    if(!c.has(first)) c.set(first, setDist(pS, gS, tbLen, first));
    return c.get(first);
  };
  const memo = new Map();
  const walk = (s0, s1, srv) => {
    if(s0 === toWin) return 1;
    if(s1 === toWin) return 0;
    const key = (s0 * 8 + s1) * 2 + srv;
    if(memo.has(key)) return memo.get(key);
    const decider = s0 === toWin - 1 && s1 === toWin - 1;
    const d = dist(decider ? finalSetTiebreak : 7, srv);
    const v = d[0] * walk(s0 + 1, s1, 0) + d[1] * walk(s0 + 1, s1, 1)
            + d[2] * walk(s0, s1 + 1, 0) + d[3] * walk(s0, s1 + 1, 1);
    memo.set(key, v);
    return v;
  };
  return walk(0, 0, firstServer);
}

// ---- public ---------------------------------------------------------------
// P(top beats bottom) for one already-drawn form pair.
function winProbForForm(top, bottom, fTop, fBot, bestOf, finalSetTiebreak, base, firstServer){
  const mu = [matchup(top, bottom, fTop, fBot, base),
              matchup(bottom, top, fBot, fTop, base)];
  const pS = [servePointProb(mu, 0), servePointProb(mu, 1)];
  return matchProbFromPoints(pS, bestOf, finalSetTiebreak, firstServer);
}

// Decide a match without playing it. Draws form and the opening server exactly
// as simMatch does, so the result is drawn from the same distribution.
function quickMatch(rng, top, bottom, bestOf, finalSetTiebreak, base){
  const fTop = drawForm(rng, top), fBot = drawForm(rng, bottom);
  const firstServer = rng.random() < 0.5 ? 0 : 1;
  const p = winProbForForm(top, bottom, fTop, fBot, bestOf, finalSetTiebreak,
                           base, firstServer);
  return { winner: rng.random() < p ? 0 : 1, p };
}

// Marginal P(top beats bottom), averaged over form. For display -- the odds
// shown next to a matchup -- not for deciding one.
function winProbability(rng, top, bottom, bestOf, finalSetTiebreak, base, draws = 200){
  let sum = 0;
  for(let i = 0; i < draws; i++){
    const fTop = drawForm(rng, top), fBot = drawForm(rng, bottom);
    sum += 0.5 * winProbForForm(top, bottom, fTop, fBot, bestOf, finalSetTiebreak, base, 0)
         + 0.5 * winProbForForm(top, bottom, fTop, fBot, bestOf, finalSetTiebreak, base, 1);
  }
  return sum / draws;
}

if(typeof module !== 'undefined') Object.assign(module.exports = {}, {
  servePointProb, gameProb, tiebreakProb, setDist, matchProbFromPoints,
  winProbForForm, quickMatch, winProbability });
