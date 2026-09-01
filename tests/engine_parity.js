/* Node side of the differential test. Reads a spec on stdin, plays each match
   with a supplied random stream instead of a generator, and prints normalised
   records. tests/test_engine_parity.py plays the same matches off the same
   stream through the Python engine and requires the output to be identical. */
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'simulation', 'engine.js'), 'utf8');
eval(src + '\nglobalThis.__simMatch = simMatch; globalThis.__matchStats = matchStats;'
     + '\nglobalThis.__setScoreStrings = setScoreStrings;');

const spec = JSON.parse(fs.readFileSync(0, 'utf8'));

// The stream stands in for the generator. Running dry means the two engines
// asked for different numbers of draws, which is itself a failure.
let ui = 0, zi = 0;
const rng = {
  random(){ if(ui >= spec.stream.length) throw new Error('uniform stream exhausted'); return spec.stream[ui++]; },
  gauss(mu, sd){ if(zi >= spec.normals.length) throw new Error('normal stream exhausted'); return mu + sd * spec.normals[zi++]; },
  shuffle(){ throw new Error('shuffle not used here'); }
};

const out = spec.matches.map(m => {
  const played = __simMatch(rng, m.top, m.bottom, ['A', 'B'], spec.bestOf, spec.finalSetTiebreak);
  const stats = __matchStats(played.sets, ['A', 'B']);   // before the score pass mutates pts
  // setScoreStrings fills in every game's score and rewrites the closing point,
  // which is exactly the text the bracket and the popup display.
  const score = __setScoreStrings(played.sets, played.winner, ['A', 'B']);
  return {
    score,
    setScores: played.sets.map(s => s.sc),
    gameScores: played.sets.map(s => s.games.map(g => g.sc)),
    pointScores: played.sets.map(s => s.games.map(g => g.pts.map(p => p[2]))),
    winner: played.winner,
    sets: played.sets.map(s => ({
      win: s.win,
      games: s.games.map(g => ({
        k: g.k, srv: g.srv, win: g.win,
        pts: g.pts.map(p => [p[0], p[1], p[3] ? 1 : 0])
      }))
    })),
    stats: stats.map(r => [r.label, r.a, r.b, r.better])
  };
});
process.stdout.write(JSON.stringify({ result: out, uniforms: ui, normals: zi }));
