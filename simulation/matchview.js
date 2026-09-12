/* The match viewer: the point-by-point panel and the point-by-point export.

   Both the grand-slam page and the season page open the same panel for a match,
   so this lives in one file rather than two. It was duplicated code waiting to
   drift -- the tiebreak serve-rotation fix in exportRows would have had to land
   twice, and only one copy is covered by tests.

   Everything a particular page knows about a match -- which tour, which round,
   the draw size, the surface, the seed that produced it -- arrives in a `ctx`
   object rather than being read from page globals:

     { round, tour, drawSize, surface, bestOf, decidingTiebreak,
       dataSet, configuration, drawSeed }

   The page owns the markup (#overlay, #mround, #mtitle, #mscore, #mbody,
   #expcsv, #expjson, #expbox) and the stylesheet; this owns what goes in them. */

// A game reads as a hold, a break, or a tiebreak; the panel colours it by that.
function outcome(g){
  if(g.k==='t') return {cls:'tbk',tag:'Tiebreak'};
  return g.win===g.srv ? {cls:'hold',tag:'Hold'} : {cls:'brk',tag:'Break'};
}

// ---- what was riding on each point ---------------------------------------
// Break, set and match points, worked out once for the whole match so the panel
// and the exported file cannot disagree about them. A point is a match point if
// winning it wins the match, a set point if it wins the set, a break point if
// the RECEIVER could win the game with it -- in that order, so a set point on
// the return is labelled as a set point and not as a break.
//
// Returns a Map keyed "setIndex:gameIndex:pointIndex" -> {stake, end}, either of
// which may be absent. `stake` is the chance the point carried -- BP, SP or MP --
// and `end`, on the point that finished the game, what it settled: B break,
// H hold, S set, M match. The deciding point usually has both.
//
// This is deliberately NOT the same thing as the export's `break_point` column.
// There the column is the raw fact -- the receiver could have won the game with
// this point -- which is what you want to count off a file. Here only one label
// goes on a point, and a set point that happens to arrive on the return reads as
// a set point. Do not "fix" either one to match the other.
function pointStakes(m, ctx){
  const out = new Map();
  const bestOf = ctx && ctx.bestOf ? ctx.bestOf : 3;
  const toWin = (bestOf + 1) / 2;
  const deciding = ctx && ctx.decidingTiebreak ? ctx.decidingTiebreak : 7;
  const sets = [0, 0];
  m.sets.forEach((set, si) => {
    // The deciding set is the only one whose tiebreak can run past seven, and
    // it is the set both players reach one short of the match.
    const isDecider = sets[0] === toWin - 1 && sets[1] === toWin - 1;
    const tbLen = isDecider ? deciding : 7;
    const games = [0, 0];
    set.g.forEach((g, gi) => {
      const tiebreak = g.k === 't';
      const pts = [0, 0];                       // points this game, by side
      // What winning the game would settle for a side, given where the set and
      // the match stand. Used twice: for the chance before a point, and for what
      // the point that ends the game actually settled.
      const settles = side => {
        const g2 = games[side] + 1, other = games[1 - side];
        const set = tiebreak || (g2 >= 6 && g2 - other >= 2) || g2 === 7;
        return { set, match: set && sets[side] + 1 >= toWin };
      };
      g.pts.forEach((p, pi) => {
        for(const side of [0, 1]){
          const mine = pts[side] + 1, theirs = pts[1 - side];
          const winsGame = tiebreak
            ? (mine >= tbLen && mine - theirs >= 2)
            : (mine >= 4 && mine - theirs >= 2);
          if(!winsGame) continue;
          const w = settles(side);
          const kind = w.match ? 'MP' : w.set ? 'SP'
                     : (!tiebreak && side !== g.srv) ? 'BP' : null;
          if(kind) out.set(si + ':' + gi + ':' + pi, { stake: { kind, side } });
        }
        pts[p[0]]++;
      });
      // The point that ended the game carries BOTH: what was riding on it and
      // what it settled. Replacing the one with the other meant a converted set
      // point showed only S -- so a match whose set and match points were all
      // taken never displayed SP or MP anywhere, which is what "MP and SP are
      // not being labelled" turned out to be.
      const lastKey = si + ':' + gi + ':' + (g.pts.length - 1);
      const w = settles(g.win);
      const prev = out.get(lastKey) || {};
      out.set(lastKey, Object.assign({}, prev, { end: {
        kind: w.match ? 'M' : w.set ? 'S' : (g.win === g.srv ? 'H' : 'B'),
        side: g.win } }));
      games[g.win]++;
    });
    sets[set.win]++;
  });
  return out;
}

// ---- how much to abbreviate ---------------------------------------------
// Nothing is abbreviated unless the panel is too narrow for the line. The
// ladder only shortens what it must, in the order the eye misses least:
//   0  full names throughout
//   1  the score line ("Ad Jessica Pegula" -> "Ad J Pegula")
//   2  the name beside the shot count as well
//   3  surnames clipped to five letters in both
const LEVELS = [
  {score: null, row: null},
  {score: 0,    row: null},
  {score: 0,    row: 0},
  {score: 5,    row: 5},
];
function levelNames(names, level){
  const spec = LEVELS[level];
  return {
    score: spec.score === null ? names : shortNames(names, spec.score),
    row:   spec.row   === null ? names : shortNames(names, spec.row),
  };
}
function rewrite(text, from, to){          // literal replace, names are not patterns
  let out = text;
  for(let i = 0; i < from.length; i++) out = out.split(from[i]).join(to[i]);
  return out;
}

// Measure with the panel's real fonts rather than guessing at character widths.
let gauge = null;
function textWidth(text, font){
  if(!gauge) gauge = document.createElement('canvas').getContext('2d');
  gauge.font = font;
  return gauge.measureText(text).width;
}
// The widest line any point in `games` would need at this level, against the
// width those games actually get.
function fitsAt(games, names, level, available, fonts){
  const n = levelNames(names, level);
  const GAPS = 12;                          // .who gap 4 + .pt gap 8
  for(const g of games){
    for(const p of g.pts){
      const who   = textWidth(n.row[p[0]], fonts.name);
      const count = textWidth(' (' + p[1] + ')', fonts.count);
      const score = textWidth(rewrite(p[2], names, n.score), fonts.score);
      if(who + count + score + GAPS > available) return false;
    }
  }
  return true;
}
function chooseLevel(games, names, available, fonts){
  for(let level = 0; level < LEVELS.length; level++){
    if(fitsAt(games, names, level, available, fonts)) return level;
  }
  return LEVELS.length - 1;                 // nothing fits; clip as hard as we can
}

// ---- the score ladder ----------------------------------------------------
// Rebuilt from the point WINNERS rather than parsed back out of the score
// string: that string is written from the server's side in a game and from the
// tiebreak opener's in a tiebreak, so reading it back would need the very
// orientation this grid is trying to drop.
// Not `PT`: engine.js already declares one at the top level, and both files are
// inlined into the same scope on both pages -- the page died on "Identifier 'PT'
// has already been declared".
const LADDER_PT = ['0', '15', '30', '40'];
function ladder(g){
  const tb = g.k === 't';
  const rows = [];
  let a = 0, b = 0;
  g.pts.forEach(p => {
    if(p[0] === 0) a++; else b++;
    let ca, cb;
    if(tb)                        { ca = String(a);  cb = String(b); }
    else if(a < 3 || b < 3)       { ca = LADDER_PT[a]; cb = LADDER_PT[b]; }
    else if(a === b)              { ca = '40';       cb = '40'; }
    else if(a > b)                { ca = 'AD';       cb = '40'; }
    else                          { ca = '40';       cb = 'AD'; }
    rows.push({ won: p[0], a: ca, b: cb, shots: p[1] });
  });
  // The last point is the game. The loser keeps the score they were on, which
  // says more than a blank -- "GM / 30" reads as the game going out at 40-30.
  const last = rows[rows.length - 1];
  if(last){
    const loser = tb ? String(g.win === 0 ? b : a) : LADDER_PT[Math.min(g.win === 0 ? b : a, 3)];
    if(g.win === 0){ last.a = 'GM'; last.b = loser; }
    else           { last.b = 'GM'; last.a = loser; }
  }
  return rows;
}

// The transposed scoreboard: a row per point, a column per player, the winner
// of each point carrying the emphasis. Rally length moves to the row's tooltip
// -- it is worth keeping, but not worth a column of its own on every point.
// A game is a handful of points and reads down; a tiebreak is one long run and
// reads across. So a game gets a row per point, and a tiebreak a COLUMN per
// point -- which also costs nothing, because a tiebreak already takes the full
// width of the panel while games sit two to a row.
function gridHtml(g, head, stakes, key){
  return g.k === 't' ? stripHtml(g, head, stakes, key)
                     : columnHtml(g, head, stakes, key);
}

// Whichever badges a point carries: what was riding on it, and what it settled.
// A tiebreak column is about thirty pixels wide and cannot hold both, so it asks
// for one: the point that ended something says what it SETTLED, and the cell
// already reads GM beside it. Chances that went begging still show BP/SP/MP.
function badgesFor(stakes, key, i, side, one){
  const st = stakes.get(key + ':' + i) || {};
  let tags = [st.stake, st.end].filter(t => t && t.side === side);
  if(one && tags.length > 1) tags = [st.end];
  return tags.map(t => '<em class="st ' + t.kind.toLowerCase() + '">' + t.kind + '</em>').join('');
}

// A game: a row per point, a column per player. One player serves throughout,
// so a single dot on their name says so.
function columnHtml(g, head, stakes, key){
  const cells = ladder(g).map((r, i) => {
    const cell = side => '<span class="pc' + (r.won === side ? ' w' : '') + '">' +
      badgesFor(stakes, key, i, side) + '<b>' + (side === 0 ? r.a : r.b) + '</b></span>';
    return '<div class="prow" title="' + r.shots + (r.shots === 1 ? ' shot' : ' shots') +
      '">' + cell(0) + cell(1) + '</div>';
  }).join('');
  const dot = side => side === g.srv ? '<i class="sv"></i>' : '';
  return '<div class="pgrid"><div class="prow ph">' +
    '<span class="pc">' + dot(0) + '<b>' + head[0] + '</b></span>' +
    '<span class="pc">' + dot(1) + '<b>' + head[1] + '</b></span></div>' + cells + '</div>';
}

// A tiebreak: a column per point, two rows, wrapping so a long one stays on the
// panel. Serve moves after the first point and every two after it -- the same
// rotation simTiebreak plays and exportRows records -- and the dot sits on
// whoever served THAT point. No separate row of point numbers: the dots already
// say where each service turn begins, and the numbers only added a third line.
const STRIP_WRAP = 8;
function stripHtml(g, head, stakes, key){
  const serverOf = pi => g.srv ^ (((pi + 1) >> 1) & 1);
  const L = ladder(g);
  // Eight to a row is the CAP, not the step: a nine-point tiebreak split 8 and 1
  // left a row holding a single point. Spread evenly over as few rows as eight
  // allows instead -- nine goes 5 and 4, twelve goes 6 and 6 -- and the columns
  // still line up, because every row is laid out on the same eight-column grid.
  const rows = Math.ceil(L.length / STRIP_WRAP);
  const per = Math.ceil(L.length / rows);
  let out = '';
  for(let b = 0; b < L.length; b += per){
    const chunk = L.slice(b, b + per);
    const line = side => '<div class="hname">' + head[side] + '</div>' +
      chunk.map((r, k) => {
        const i = b + k;
        const turn = i > 0 && serverOf(i) !== serverOf(i - 1) ? ' turn' : '';
        return '<div class="hc' + (r.won === side ? ' w' : '') + turn + '" title="' +
          r.shots + (r.shots === 1 ? ' shot' : ' shots') + ', ' +
          head[serverOf(i)] + ' serving">' + badgesFor(stakes, key, i, side, true) +
          (serverOf(i) === side ? '<i class="sv"></i>' : '') +
          '<b>' + (side === 0 ? r.a : r.b) + '</b></div>';
      }).join('') +
      Array(STRIP_WRAP - chunk.length).fill('<div class="hc pad"></div>').join('');
    out += '<div class="hblock">' + line(0) + line(1) + '</div>';
  }
  return '<div class="hgrid">' + out + '</div>';
}


// The long-standing view, left exactly as it was: who won each point, how many
// shots it took, and the running score written out. Kept alongside the grid
// rather than replaced -- the rally lengths and the written score are the reason
// to open it at all. The BP/SP/MP and B/H/S/M badges deliberately do NOT appear
// here: this layout puts the name first and a badge in front of it shunts the
// whole column sideways on the rows that have one.
function detailHtml(g, names, head, level){
  const n=levelNames(names, level);
  return g.pts.map(p=>'<div class="pt"><span class="who">'+
    '<span class="pn">'+n.row[p[0]]+'</span>'+
    '<span class="n">('+p[1]+')</span></span>'+
    '<span class="sc">'+rewrite(p[2], names, n.score)+'</span></div>').join('');
}

// full names in the header, clipped ones on the points beneath it
function gameHtml(g, names, head, level, stakes, key, mode){
  const o=outcome(g);
  const serve = g.k==='t' ? '' : '<span class="srv">serve <b>'+head[g.srv]+'</b></span>';
  const body = mode==='detail' ? detailHtml(g, names, head, level)
                               : gridHtml(g, head, stakes, key);
  return '<div class="game '+o.cls+'"><button class="ghead"><span class="gchev">&#9654;</span>'+
    '<span class="tag">'+o.tag+'</span>'+serve+'<span class="gwin">'+head[g.win]+'</span>'+
    '<span class="gsc">'+g.sc+'</span></button><div class="pts">'+body+'</div></div>';
}
// Two or four game panels per row, never three and never one where two fit --
// a bracket reads in halves, and an odd column count breaks that rhythm.
const GAME_MIN = 198, GAME_GAP = 7;
// Widest header this match can produce: the longer name in both the serve slot
// and the winner slot, with the widest tag. Measured by laying one out rather
// than adding up guesses, so letter-spacing and font fallbacks are included.
function headerWidth(names, host){
  const longest = names[0].length >= names[1].length ? names[0] : names[1];
  const probe = document.createElement('div');
  probe.className = 'game';
  probe.style.cssText = 'position:absolute;visibility:hidden;width:max-content';
  probe.innerHTML = '<button class="ghead"><span class="gchev">&#9654;</span>' +
    '<span class="tag">Tiebreak</span><span class="srv">serve <b>' + longest + '</b></span>' +
    '<span class="gwin">' + longest + '</span><span class="gsc">6(10)-7</span></button>';
  host.appendChild(probe);
  const width = probe.getBoundingClientRect().width;
  probe.remove();
  return width;
}
// Two or four panels per row, never three. Four only when full names fit that
// narrow; otherwise two wide panels, which read better and leave the header room
// to shorten instead of the layout collapsing to a single column. One column is
// for genuinely narrow screens, not for long names.
function gameColumns(width, names, host){
  const panelAt = k => (width - (k - 1) * GAME_GAP) / k;
  const room = Math.floor((width + GAME_GAP) / (GAME_MIN + GAME_GAP));
  for(const k of [4, 2]) if(k <= room && headerWidth(names, host) <= panelAt(k)) return k;
  return room >= 2 ? 2 : 1;
}

// Headers shorten on the same principle as the points: full names, then first
// initial, then a clipped surname -- each step only if the one before overflows.
const HEADER_LEVELS = [null, 0, 5];
// The point ladder rung that shows the same form as each header rung, so the
// header is never more abbreviated than the rows underneath it.
const HEADER_TO_POINT = [0, 2, 3];
function headerLevelFor(names, host, panel){
  for(let i = 0; i < HEADER_LEVELS.length; i++){
    const shown = HEADER_LEVELS[i] === null ? names : shortNames(names, HEADER_LEVELS[i]);
    if(headerWidth(shown, host) <= panel) return i;
  }
  return HEADER_LEVELS.length - 1;
}
function headerNames(names, level){
  return HEADER_LEVELS[level] === null ? names : shortNames(names, HEADER_LEVELS[level]);
}
// The panel's own fonts, read off a probe rather than assumed.
function panelFonts(host){
  const probe = document.createElement('div');
  probe.className = 'pt';
  probe.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none';
  probe.innerHTML = '<span class="who"><span class="pn">x</span>' +
                    '<span class="n">(1)</span></span><span class="sc">0 - 0</span>';
  host.appendChild(probe);
  const font = node => {
    const c = getComputedStyle(node);
    return c.fontStyle + ' ' + c.fontWeight + ' ' + c.fontSize + ' ' + c.fontFamily;
  };
  const fonts = { name: font(probe.querySelector('.pn')),
                  count: font(probe.querySelector('.n')),
                  score: font(probe.querySelector('.sc')) };
  probe.remove();
  return fonts;
}


// ---- point-by-point export -------------------------------------------------
// One row per point. Everything here is derived from the match record rather
// than re-simulated, so the file describes exactly the match on screen.
function exportRows(m){
  const names = m.statNames;
  const rows = [];
  let pointNo = 0, gameNo = 0;
  m.sets.forEach((set, si) => {
    let gameInSet = 0;
    set.g.forEach(g => {
      gameNo++;
      const tiebreak = g.k === 't';
      gameInSet++;                     // the tiebreak is the set's 13th game
      // g.srv is whoever served the FIRST point. In a game that server holds
      // throughout; in a tiebreak serve rotates after the 1st point and every
      // two points after it, so point i (1-based) is served by g.srv flipped
      // floor(i/2) times -- the same rule simTiebreak plays out.
      const serverOf = pi => tiebreak ? (g.srv ^ (((pi + 1) >> 1) & 1)) : g.srv;
      let sp = 0, rp = 0;              // server / receiver points so far in this game
      g.pts.forEach((pt, pi) => {
        const [winner, shots, , firstServe] = pt;
        const doubleFault = shots === 0;
        const server = serverOf(pi), receiver = 1 - server;
        // A break point is one the RECEIVER could win the game with. Tiebreaks
        // have no break points -- serve rotates, so no game is being held.
        const needed = rp + 1;
        const breakPoint = !tiebreak && needed >= 4 && needed - sp >= 2;
        pointNo++;
        rows.push({
          overall_point: pointNo,
          overall_game: gameNo,
          set: si + 1,
          game: gameInSet,
          tiebreak: tiebreak ? 1 : 0,
          point_in_game: pi + 1,
          server: names[server],
          returner: names[receiver],
          winner: names[winner],
          server_won: winner === server ? 1 : 0,
          break_point: breakPoint ? 1 : 0,
          break_point_converted: breakPoint && winner === receiver ? 1 : 0,
          serve: doubleFault ? 'double_fault' : (firstServe ? 'first' : 'second'),
          unreturned_serve: shots === 1 ? 1 : 0,
          shots: shots,
          score_after: pt[2],
        });
        if(winner === server) sp++; else rp++;
      });
    });
  });
  return rows;
}

function exportMeta(m, ctx){
  return {
    tour: ctx.tour, round: ctx.round, draw_size: ctx.drawSize,
    surface: ctx.surface, best_of: ctx.bestOf, deciding_tiebreak: ctx.decidingTiebreak,
    data_set: ctx.dataSet, configuration: ctx.configuration,
    draw_seed: ctx.drawSeed != null ? ctx.drawSeed : null,
    players: m.statNames, score: m.score,
  };
}

function exportJSON(m, ctx){
  // Summary statistics ride along here, where nesting is free.
  return JSON.stringify({
    match: exportMeta(m, ctx),
    summary: m.stats.map(r => ({ statistic: r.label, [m.statNames[0]]: r.a,
                                 [m.statNames[1]]: r.b, better: r.better })),
    points: exportRows(m),
  }, null, 2);
}

function exportCSV(m, ctx){
  const rows = exportRows(m);
  const cols = Object.keys(rows[0]);
  const cell = v => {
    const t = String(v ?? '');
    return /[",\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
  };
  // CSV has nowhere structured to put the summary, so it goes in a commented
  // header. Every common reader can skip it: pandas read_csv(comment='#'),
  // R read.csv(comment.char='#'), csvkit --skip-lines.
  const meta = exportMeta(m, ctx);
  const head = Object.entries(meta)
    .map(([k, v]) => '# ' + k + ': ' + (Array.isArray(v) ? v.join(' v ') : v));
  const summary = m.stats.map(r =>
    '# ' + r.label + ': ' + r.a + ' | ' + r.b);
  return head.concat(['#', '# --- match statistics (' + m.statNames.join(' | ') + ') ---'],
                     summary, ['#'])
    .concat([cols.join(',')], rows.map(r => cols.map(c => cell(r[c])).join(',')))
    .join('\n') + '\n';
}

function slug(m, ctx){
  return (m.statNames.join('-v-') + '-' + (ctx.tour || '') + '-' + (ctx.drawSize || ''))
    .replace(/[^A-Za-z0-9-]+/g, '_');
}
// Saving a file takes two different routes. On an ordinary web host an anchor
// with `download` is all there is. Inside the claude.ai viewer the frame may not
// download directly at all, and the `downloads` capability mediates it instead --
// the viewer sees a confirmation and can decline. `claude.use` resolves late and
// resolves null wherever the capability is not served, so this is asked once at
// load and both routes end at the same copy-out box if neither works.
const downloadsReady = (typeof window.claude === 'object' && window.claude
                        && typeof window.claude.use === 'function')
  ? Promise.resolve(window.claude.use('downloads')).catch(() => null)
  : Promise.resolve(null);

function showCopyBox(text){
  const box = document.getElementById('expbox');
  box.value = text;
  box.hidden = false;
  box.focus();
  box.select();
}

async function offerDownload(text, filename, type){
  const downloads = await downloadsReady;
  if(downloads){
    try {
      await downloads.save({ filename, data: text });
      return;                                   // the viewer accepted it
    } catch (err) {
      // Declining is an answer, not a failure: never retry, never fall back.
      if(err && err.code === 'declined') return;
    }
  } else {
    try {
      const url = URL.createObjectURL(new Blob([text], { type }));
      const a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return;
    } catch (err) { /* sandboxed: fall through */ }
  }
  showCopyBox(text);
}

// Which of the two point views the panel shows. Remembered across matches and
// across visits: whichever one you read in, you almost certainly want again.
const VIEW_KEY = 'tennis:pointview';   // one namespace across the whole site
// Held in memory, with storage only as the way it survives a reload. Reading it
// back from localStorage on every render made the control dead wherever storage
// throws -- a private window, a browser set to block site data -- because the
// write was swallowed and the next read returned the old value. Same shape as
// the bug that made the season's pause button unclickable.
let viewPref = null;
function viewMode(){
  if(viewPref === null){
    try { viewPref = localStorage.getItem(VIEW_KEY) === 'detail' ? 'detail' : 'grid'; }
    catch(e){ viewPref = 'grid'; }
  }
  return viewPref;
}
function setViewMode(v){
  viewPref = v;
  try { localStorage.setItem(VIEW_KEY, v); } catch(e){}
}
function wireViewToggle(m, ctx){
  const box = document.getElementById('mview');
  if(!box) return;                         // a page that has not added the control
  const mode = viewMode();
  box.innerHTML = ['grid', 'detail'].map(k =>
    '<button type="button" class="vbtn' + (k === mode ? ' on' : '') + '" data-v="' + k +
    '">' + (k === 'grid' ? 'Score' : 'Detail') + '</button>').join('');
  box.querySelectorAll('.vbtn').forEach(b => b.addEventListener('click', () => {
    if(b.dataset.v === viewMode()) return;
    setViewMode(b.dataset.v);
    // Re-open rather than re-render in place: the abbreviation ladder is chosen
    // from the width the panel actually has, and that is what openMatch does.
    const open = [...document.querySelectorAll('#mbody .game')]
      .map(g => g.classList.contains('open'));
    openMatch(m, ctx);
    document.querySelectorAll('#mbody .game')
      .forEach((g, i) => g.classList.toggle('open', !!open[i]));
  }));
}

function openMatch(m, ctx){
  const overlay=document.getElementById('overlay');
  document.getElementById('mround').textContent=ctx.round||'';
  // statNames is the pair of players and is present on every match record; the
  // grand-slam page's top/bottom seats are not, so they are not relied on here.
  document.getElementById('mtitle').textContent=m.statNames[0]+' v '+m.statNames[1];
  document.getElementById('mscore').textContent=m.score;

  // Open first: the panel has to be laid out before it can be measured.
  overlay.classList.add('open');
  document.body.style.overflow='hidden';
  const body=document.getElementById('mbody');
  const names=m.statNames;

  const width=body.clientWidth;
  const cols=gameColumns(width, names, body);
  body.style.setProperty('--gamecols', cols);
  const fonts=panelFonts(body);
  const PAD=18;                                   // .pts padding, 9px each side
  const panelWidth=(width - (cols-1)*GAME_GAP)/cols;
  const regularWidth=panelWidth - PAD;
  const tiebreakWidth=width - PAD;                // a tiebreak takes the whole row
  const headLevel=headerLevelFor(names, body, panelWidth);
  const head=headerNames(names, headLevel);
  const floor=HEADER_TO_POINT[headLevel];   // points never read longer than the header

  const all=m.sets.flatMap(s=>s.g);
  const regularLevel=Math.max(floor, chooseLevel(all.filter(g=>g.k!=='t'), names, regularWidth, fonts));
  const tiebreakLevel=Math.max(floor, chooseLevel(all.filter(g=>g.k==='t'), names, tiebreakWidth, fonts));

  const stakes=pointStakes(m, ctx);
  const mode=viewMode();
  const sets=m.sets.map((s,i)=>
    '<div class="setrow"><div class="setlabel"><span>Set '+(i+1)+'</span><span class="s">'+s.sc+
    '</span><span style="color:var(--muted)">'+names[s.win]+'</span></div>'+
    '<div class="games">'+s.g.map((g,gi)=>
      gameHtml(g,names,head,g.k==='t'?tiebreakLevel:regularLevel,
               stakes,i+':'+gi,mode)).join('')+'</div></div>').join('');
  const rows=m.stats.map(r=>
    '<div class="srow"><span class="v l'+(r.better==='a'?' best':'')+'">'+r.a+'</span>'+
    '<span class="k">'+r.label+'</span>'+
    '<span class="v r'+(r.better==='b'?' best':'')+'">'+r.b+'</span></div>').join('');
  body.innerHTML = sets +
    '<div class="stats"><h3><span class="who">'+m.statNames[0]+'</span><span>Match statistics</span>'+
    '<span class="who">'+m.statNames[1]+'</span></h3>'+rows+'</div>';
  body.querySelectorAll('.ghead').forEach(h=>
    h.addEventListener('click',()=>h.parentElement.classList.toggle('open')));
  wireViewToggle(m, ctx);
  document.getElementById('expbox').hidden = true;
  document.getElementById('expcsv').onclick = () =>
    offerDownload(exportCSV(m, ctx), slug(m, ctx) + '-points.csv', 'text/csv');
  document.getElementById('expjson').onclick = () =>
    offerDownload(exportJSON(m, ctx), slug(m, ctx) + '.json', 'application/json');
  overlay.querySelector('.modal').scrollTop = 0;   // .modal scrolls, not .mbody
}
function closeMatch(){
  const overlay=document.getElementById('overlay');
  overlay.classList.remove('open');
  document.body.style.overflow='';
}