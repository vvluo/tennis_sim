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

// full names in the header, clipped ones on the points beneath it
function gameHtml(g, names, head, level){
  const o=outcome(g);
  const n=levelNames(names, level);
  const serve = g.k==='t' ? '' : '<span class="srv">serve <b>'+head[g.srv]+'</b></span>';
  // The shot count is its own element so that a long score line ("Game Set
  // Match ...") clips the NAME rather than eating the count off the end.
  const pts=g.pts.map(p=>'<div class="pt"><span class="who">'+
    '<span class="pn">'+n.row[p[0]]+'</span>'+
    '<span class="n">('+p[1]+')</span></span>'+
    '<span class="sc">'+rewrite(p[2], names, n.score)+'</span></div>').join('');
  return '<div class="game '+o.cls+'"><button class="ghead"><span class="gchev">&#9654;</span>'+
    '<span class="tag">'+o.tag+'</span>'+serve+'<span class="gwin">'+head[g.win]+'</span>'+
    '<span class="gsc">'+g.sc+'</span></button><div class="pts">'+pts+'</div></div>';
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

  const sets=m.sets.map((s,i)=>
    '<div class="setrow"><div class="setlabel"><span>Set '+(i+1)+'</span><span class="s">'+s.sc+
    '</span><span style="color:var(--muted)">'+names[s.win]+'</span></div>'+
    '<div class="games">'+s.g.map(g=>
      gameHtml(g,names,head,g.k==='t'?tiebreakLevel:regularLevel)).join('')+'</div></div>').join('');
  const rows=m.stats.map(r=>
    '<div class="srow"><span class="v l'+(r.better==='a'?' best':'')+'">'+r.a+'</span>'+
    '<span class="k">'+r.label+'</span>'+
    '<span class="v r'+(r.better==='b'?' best':'')+'">'+r.b+'</span></div>').join('');
  body.innerHTML = sets +
    '<div class="stats"><h3><span class="who">'+m.statNames[0]+'</span><span>Match statistics</span>'+
    '<span class="who">'+m.statNames[1]+'</span></h3>'+rows+'</div>';
  body.querySelectorAll('.ghead').forEach(h=>
    h.addEventListener('click',()=>h.parentElement.classList.toggle('open')));
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