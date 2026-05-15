// ─── State ────────────────────────────────────────────────────────────────────
const state = {
  sentences: [],        // current round's sentence list
  allSentences: [],     // full loaded set
  videoId: null,
  idx: 0,
  revealed: false,
  settings: { writeKorean: true, translateEnglish: true },
  scores: {},           // { id: true | false }
  koreanCorrect: null,
  englishCorrect: null,
  resultRecorded: false,
  roundCorrect: 0,
};

// ─── Audio player ─────────────────────────────────────────────────────────────
function setPlayBtn(playing) {
  el('play-btn').textContent = playing ? '⏸' : '▶';
}

function playSegment() {
  const audio = el('audio-player');
  if (!audio.paused) { audio.pause(); return; }
  const s = state.sentences[state.idx];
  if (audio.dataset.sentenceId !== String(s.id)) {
    audio.src = s.audio_url;
    audio.dataset.sentenceId = s.id;
  }
  audio.play();
}

function replaySegment() {
  const s = state.sentences[state.idx];
  const audio = el('audio-player');
  audio.src = s.audio_url;
  audio.dataset.sentenceId = s.id;
  audio.currentTime = 0;
  audio.play();
}

function initAudioListeners() {
  const audio = el('audio-player');
  audio.addEventListener('play',  () => setPlayBtn(true));
  audio.addEventListener('pause', () => setPlayBtn(false));
  audio.addEventListener('ended', () => setPlayBtn(false));
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
const el = id => document.getElementById(id);

function show(...ids) { ids.forEach(id => el(id).classList.remove('hidden')); }
function hide(...ids) { ids.forEach(id => el(id).classList.add('hidden')); }

function normalize(text) {
  return (text || '').normalize('NFC').trim().replace(/\s+/g, ' ');
}

function escHtml(str) {
  return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function saveSettings() {
  localStorage.setItem('kp-settings', JSON.stringify(state.settings));
}

function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem('kp-settings') || '{}');
    if (typeof s.writeKorean    === 'boolean') state.settings.writeKorean    = s.writeKorean;
    if (typeof s.translateEnglish === 'boolean') state.settings.translateEnglish = s.translateEnglish;
  } catch (_) {}
}

// ─── Score tracking ───────────────────────────────────────────────────────────
function recordResult() {
  if (state.resultRecorded) return;
  state.resultRecorded = true;

  const listenOnly = !state.settings.writeKorean && !state.settings.translateEnglish;
  let correct;

  if (listenOnly) {
    correct = true;
  } else {
    const koreanOk = state.settings.writeKorean ? (state.koreanCorrect === true) : true;
    const englishOk = (state.settings.translateEnglish && state.englishCorrect !== null)
      ? state.englishCorrect : true;
    correct = koreanOk && englishOk;
  }

  const s = state.sentences[state.idx];
  state.scores[s.id] = correct;
  if (correct) state.roundCorrect++;
  updateScoreCounter();
}

function updateScoreCounter() {
  el('score-text').textContent = `✓ ${state.roundCorrect} / ${state.sentences.length}`;
}

// ─── Round management ─────────────────────────────────────────────────────────
function startRound(sentences) {
  state.sentences = sentences;
  state.idx = 0;
  state.roundCorrect = 0;
  state.scores = {};
  sentences.forEach(s => { state.scores[s.id] = null; });

  hide('load-screen', 'configure-screen', 'round-complete-screen');
  show('practice-screen');
  el('play-btn').disabled  = false;
  el('replay-btn').disabled = false;
  updateScoreCounter();
  renderCard();
}

function finishRound() {
  hide('practice-screen');

  const wrongSentences = state.sentences.filter(s => state.scores[s.id] === false);
  el('round-result-text').textContent =
    `You got ${state.roundCorrect} out of ${state.sentences.length} correct.`;

  if (wrongSentences.length === 0) {
    el('round-badge').textContent = '🎉 All correct!';
    hide('retry-wrong-btn');
    show('round-done-btn');
  } else {
    el('round-badge').textContent = `${wrongSentences.length} to retry`;
    el('retry-wrong-btn').textContent = `Retry ${wrongSentences.length} missed →`;
    el('retry-wrong-btn').onclick = () => startRound(wrongSentences);
    show('retry-wrong-btn');
    hide('round-done-btn');
  }
  show('round-complete-screen');
}

// ─── Configure screen ─────────────────────────────────────────────────────────
function showConfigure(name, sentences) {
  state.allSentences = sentences;
  state.videoId = name;

  el('configure-set-name').textContent = name;
  const total = sentences.length;
  const counts = [10, 25, 50].filter(n => n < total);
  counts.push(total);

  const container = el('count-options');
  container.innerHTML = counts.map(n =>
    `<button class="count-option-btn" data-count="${n}">
       ${n === total ? `All (${n})` : n}
     </button>`
  ).join('');

  container.querySelectorAll('.count-option-btn').forEach(btn => {
    btn.addEventListener('click', () =>
      startRound(state.allSentences.slice(0, parseInt(btn.dataset.count)))
    );
  });

  hide('load-screen', 'practice-screen', 'round-complete-screen');
  show('configure-screen');
}

// ─── Load video (URL) ─────────────────────────────────────────────────────────
async function loadVideo(url) {
  hide('load-error');
  el('load-btn').disabled = true;
  el('load-btn').textContent = 'Processing…';

  try {
    const res = await fetch('/api/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!res.ok) { showLoadError(data.error || 'Something went wrong.'); return; }
    if (!data.sentences?.length) { showLoadError('No sentences found.'); return; }

    showConfigure(data.video_id, data.sentences);
  } catch (e) {
    showLoadError('Network error: ' + e.message);
  } finally {
    el('load-btn').disabled = false;
    el('load-btn').textContent = 'Load';
  }
}

function showLoadError(msg) {
  el('load-error').textContent = msg;
  show('load-error');
}

// ─── Practice ─────────────────────────────────────────────────────────────────
function renderCard() {
  state.revealed = false;
  state.koreanCorrect  = null;
  state.englishCorrect = null;
  state.resultRecorded = false;

  el('audio-player').pause();
  setPlayBtn(false);

  const s     = state.sentences[state.idx];
  const total = state.sentences.length;

  el('progress-fill').style.width  = `${(state.idx / total) * 100}%`;
  el('progress-text').textContent  = `${state.idx + 1} / ${total}`;

  el('korean-input').value     = '';
  el('english-input').value    = '';
  el('korean-input').className  = '';
  el('english-input').className = '';

  state.settings.writeKorean      ? show('korean-group')  : hide('korean-group');
  state.settings.translateEnglish ? show('english-group') : hide('english-group');

  if (!s.english && state.settings.translateEnglish) {
    el('english-group-label').textContent = 'Translate to English (not available)';
    el('english-input').disabled = true;
  } else {
    el('english-group-label').textContent = 'Translate to English';
    el('english-input').disabled = false;
  }

  hide('answer-reveal', 'self-assess-row', 'next-btn');
  show('check-btn', 'skip-btn');

  const listenOnly = !state.settings.writeKorean && !state.settings.translateEnglish;
  el('check-btn').textContent = listenOnly ? 'Reveal' : 'Check Answer';

  if (state.settings.writeKorean) el('korean-input').focus();
  else if (state.settings.translateEnglish) el('english-input').focus();
}

function checkAnswer() {
  if (state.revealed) return;
  state.revealed = true;

  const s = state.sentences[state.idx];
  hide('check-btn', 'skip-btn');

  let revealHTML = '';
  let needSelfAssess = false;

  if (state.settings.writeKorean) {
    const input    = normalize(el('korean-input').value);
    const expected = normalize(s.korean);
    state.koreanCorrect = input === expected;
    const tag = state.koreanCorrect
      ? '<span class="feedback-tag correct">✓ Correct</span>'
      : '<span class="feedback-tag incorrect">✗ Incorrect</span>';
    el('korean-input').className = state.koreanCorrect ? 'correct' : 'incorrect';
    revealHTML += `
      <div class="answer-block korean">
        <span class="answer-label">Korean</span>
        <span class="answer-text">${escHtml(s.korean)}</span>
        ${tag}
      </div>`;
  } else {
    revealHTML += `
      <div class="answer-block korean">
        <span class="answer-label">Korean</span>
        <span class="answer-text">${escHtml(s.korean)}</span>
      </div>`;
  }

  if (s.english) {
    revealHTML += `
      <div class="answer-block">
        <span class="answer-label">English</span>
        <span class="answer-text">${escHtml(s.english)}</span>
      </div>`;
    if (state.settings.translateEnglish && el('english-input').value.trim()) {
      needSelfAssess = true;
    }
  }

  el('answer-reveal').innerHTML = revealHTML;
  show('answer-reveal');

  if (needSelfAssess) {
    show('self-assess-row');
  } else {
    recordResult();
    show('next-btn');
  }
}

function selfAssess(correct) {
  state.englishCorrect = correct;
  recordResult();
  hide('self-assess-row');
  show('next-btn');
}

function nextCard() {
  recordResult(); // no-op if already recorded
  state.idx++;
  if (state.idx >= state.sentences.length) finishRound();
  else renderCard();
}

function goToLoadScreen() {
  hide('practice-screen', 'round-complete-screen', 'configure-screen');
  show('load-screen');
  el('video-url').value = '';
}

// ─── Settings ─────────────────────────────────────────────────────────────────
function applySettingsToUI() {
  el('setting-write-korean').checked = state.settings.writeKorean;
  el('setting-translate').checked    = state.settings.translateEnglish;
}

function onSettingChange() {
  state.settings.writeKorean      = el('setting-write-korean').checked;
  state.settings.translateEnglish = el('setting-translate').checked;
  saveSettings();
  if (state.sentences.length > 0 && !state.revealed) renderCard();
}

// ─── Local pre-processed sets ─────────────────────────────────────────────────
async function fetchLocalSets() {
  try {
    const res = await fetch('/api/local-sets');
    const { sets } = await res.json();
    if (!sets?.length) return;

    const list = el('local-sets-list');
    list.innerHTML = sets.map(s => `
      <button class="local-set-btn" data-name="${escHtml(s.name)}">
        <span class="local-set-name">${escHtml(s.name)}</span>
        <span class="local-set-right">
          ${s.difficulty ? `<span class="difficulty-badge difficulty-${escHtml(s.difficulty)}">${escHtml(s.difficulty)}</span>` : ''}
          <span class="local-set-count">${s.sentence_count} sentences</span>
        </span>
      </button>
    `).join('');

    list.querySelectorAll('.local-set-btn').forEach(btn => {
      btn.addEventListener('click', () => loadLocalSet(btn.dataset.name));
    });

    show('local-sets-area');
  } catch (_) {}
}

async function loadLocalSet(name) {
  hide('load-error');
  try {
    const res  = await fetch(`/api/local-sets/${encodeURIComponent(name)}/sentences`);
    const data = await res.json();
    if (!res.ok)          { showLoadError(data.error || 'Failed to load.'); return; }
    if (!data.sentences?.length) { showLoadError('No sentences found.');    return; }
    showConfigure(name, data.sentences);
  } catch (e) {
    showLoadError('Network error: ' + e.message);
  }
}

// ─── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  applySettingsToUI();
  fetchLocalSets();

  el('load-btn').addEventListener('click', () => {
    const url = el('video-url').value.trim();
    if (url) loadVideo(url);
  });
  el('video-url').addEventListener('keydown', e => {
    if (e.key === 'Enter') el('load-btn').click();
  });

  initAudioListeners();
  el('play-btn').addEventListener('click',   playSegment);
  el('replay-btn').addEventListener('click', replaySegment);

  el('check-btn').addEventListener('click', checkAnswer);
  el('skip-btn').addEventListener('click',  checkAnswer);

  el('got-it-btn').addEventListener('click', () => selfAssess(true));
  el('missed-btn').addEventListener('click', () => selfAssess(false));

  el('next-btn').addEventListener('click', nextCard);

  el('setting-write-korean').addEventListener('change', onSettingChange);
  el('setting-translate').addEventListener('change',    onSettingChange);

  el('main-menu-btn').addEventListener('click',    goToLoadScreen);
  el('change-video-btn').addEventListener('click',  goToLoadScreen);
  el('restart-btn').addEventListener('click', () => showConfigure(state.videoId, state.allSentences));

  el('round-done-btn').addEventListener('click',      goToLoadScreen);
  el('round-new-video-btn').addEventListener('click', goToLoadScreen);

  el('configure-back-btn').addEventListener('click', () => {
    hide('configure-screen');
    show('load-screen');
  });

  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT') return;
    if (e.code === 'Space') { e.preventDefault(); playSegment(); }
    if (e.code === 'Enter') {
      if (!state.revealed) checkAnswer();
      else if (!el('next-btn').classList.contains('hidden')) nextCard();
    }
  });
});
