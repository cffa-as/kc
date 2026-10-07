// 5x5 排雷下一步推荐器
// 核心：贝叶斯概率传播 + DFS 枚举合法星位配置

const N = 5;
const TOTAL_STARS = 9;
const INIT_PROB = TOTAL_STARS / (N * N); // 0.36

// 预计算 8 邻居（边缘格子按实际 3/5/8 算）
const NEIGHBORS = [];
for (let r = 0; r < N; r++) {
    NEIGHBORS.push([]);
    for (let c = 0; c < N; c++) {
        const nbs = [];
        for (let dr = -1; dr <= 1; dr++) {
            for (let dc = -1; dc <= 1; dc++) {
                if (dr === 0 && dc === 0) continue;
                const nr = r + dr;
                const nc = c + dc;
                if (nr >= 0 && nr < N && nc >= 0 && nc < N) {
                    nbs.push(nr * N + nc);
                }
            }
        }
        NEIGHBORS[r].push(nbs);
    }
}

// 全局状态
let probs = [];           // probs[r][c] = 是星的概率
let revealed = [];        // {r, c, isStar, number}
let steps = 0;
let starsFound = 0;

function initProbs() {
    probs = [];
    for (let r = 0; r < N; r++) {
        probs.push(new Array(N).fill(INIT_PROB));
    }
}

function reset() {
    initProbs();
    revealed = [];
    steps = 0;
    starsFound = 0;
    renderBoard();
    renderStats();
    renderRecommend();
    hideToast();
}

// 收集所有未翻格的扁平 id (r*N+c)
function getUnrevealedIds() {
    const revSet = new Set(revealed.map(x => x.r * N + x.c));
    const out = [];
    for (let i = 0; i < N * N; i++) {
        if (!revSet.has(i)) out.push(i);
    }
    return out;
}

// 构建约束：从每个非星已翻格出发
// 约束 = "周围未翻格中恰好 remaining 个是星"，其中 remaining = N - 已翻开邻居中的星数
function buildConstraints() {
    const constraints = [];
    const revSet = new Set(revealed.map(x => x.r * N + x.c));

    for (const rev of revealed) {
        if (rev.isStar) continue;

        const allNbs = NEIGHBORS[rev.r][rev.c];
        const unrevNbs = [];
        let knownStars = 0;
        for (const nid of allNbs) {
            if (revSet.has(nid)) {
                const r = revealed.find(x => x.r * N + x.c === nid);
                if (r.isStar) knownStars++;
            } else {
                unrevNbs.push(nid);
            }
        }
        const remaining = rev.number - knownStars;
        if (remaining < 0 || remaining > unrevNbs.length) {
            // 矛盾约束，无合法配置
            return { ok: false };
        }
        constraints.push({ remaining, cells: unrevNbs });
    }
    return { ok: true, constraints };
}

// DFS 枚举所有满足约束的星位配置
// _cells: 所有被约束涉及到的未翻格 id 数组
// _constraints: 约束数组，每个约束是 {remaining, cells: [未翻格 id]}
// _cellIdx: Map<未翻格 id, _cells 内的索引>
// _config: 当前正在构建的配置（true=是星）
// _counts: 每个未翻格被选为星的次数
// _total: 合法配置总数

let _cells, _cellIdx, _constraints;
let _counts, _total;

function dfs(config, conIdx) {
    if (conIdx === _constraints.length) {
        _total++;
        for (let i = 0; i < _cells.length; i++) {
            if (config[i]) _counts[i]++;
        }
        return;
    }

    const con = _constraints[conIdx];
    if (con.cells.length === 0) {
        if (con.remaining === 0) dfs(config, conIdx + 1);
        return;
    }

    if (con.remaining < 0 || con.remaining > con.cells.length) return;

    // 把约束内的未翻格 id 映射到 _cells 内的索引
    const localIdxs = con.cells.map(id => _cellIdx.get(id));

    // 枚举选 con.remaining 个星
    const picked = new Array(localIdxs.length).fill(false);
    function pick(start, left) {
        if (left === 0) {
            // 把 picked 写入 config
            const backup = new Array(localIdxs.length);
            for (let k = 0; k < localIdxs.length; k++) {
                backup[k] = config[localIdxs[k]];
                config[localIdxs[k]] = picked[k];
            }
            dfs(config, conIdx + 1);
            for (let k = 0; k < localIdxs.length; k++) {
                config[localIdxs[k]] = backup[k];
            }
            return;
        }
        for (let i = start; i <= localIdxs.length - left; i++) {
            picked[i] = true;
            pick(i + 1, left - 1);
            picked[i] = false;
        }
    }
    pick(0, con.remaining);
}

function enumerateLegalConfigs() {
    const result = buildConstraints();
    if (!result.ok) return { ok: false };
    _constraints = result.constraints;

    // 收集所有约束涉及的未翻格 id（去重）
    const cellSet = new Set();
    for (const con of _constraints) {
        for (const id of con.cells) cellSet.add(id);
    }
    _cells = Array.from(cellSet);
    _cellIdx = new Map(_cells.map((id, i) => [id, i]));
    _counts = new Array(_cells.length).fill(0);
    _total = 0;

    if (_cells.length === 0) return { ok: true, counts: [], total: 0, cells: [] };

    dfs(new Array(_cells.length).fill(false), 0);
    return { ok: true, counts: _counts, total: _total, cells: _cells };
}

function updateProbabilities() {
    const result = enumerateLegalConfigs();
    if (!result.ok) return false;
    if (result.total === 0) return false;

    const { counts, total, cells } = result;
    const idToCount = new Map();
    cells.forEach((id, i) => idToCount.set(id, counts[i]));

    for (let r = 0; r < N; r++) {
        for (let c = 0; c < N; c++) {
            const id = r * N + c;
            if (idToCount.has(id)) {
                probs[r][c] = idToCount.get(id) / total;
            }
            // 不在约束涉及的未翻格 -> 保持原概率
        }
    }
    return true;
}

function getBestCell() {
    let best = null;
    let bestP = -1;
    const revSet = new Set(revealed.map(x => x.r * N + x.c));
    for (let r = 0; r < N; r++) {
        for (let c = 0; c < N; c++) {
            const id = r * N + c;
            if (revSet.has(id)) continue;
            if (probs[r][c] > bestP) {
                bestP = probs[r][c];
                best = { r, c, p: bestP };
            }
        }
    }
    return best;
}

// ========== UI 渲染 ==========

function renderBoard() {
    const board = document.getElementById('board');
    board.innerHTML = '';
    const best = getBestCell();
    const revMap = new Map(revealed.map(x => [x.r * N + x.c, x]));

    for (let r = 0; r < N; r++) {
        for (let c = 0; c < N; c++) {
            const cell = document.createElement('div');
            cell.className = 'cell';
            const id = r * N + c;
            const rev = revMap.get(id);
            if (rev) {
                cell.classList.add('revealed');
                if (rev.isStar) {
                    cell.classList.add('star');
                    cell.textContent = '★';
                } else {
                    cell.classList.add('n' + rev.number);
                    cell.textContent = rev.number;
                }
            } else {
                if (best && best.r === r && best.c === c) {
                    cell.classList.add('best');
                }
                cell.addEventListener('click', () => onCellClick(r, c));
            }
            board.appendChild(cell);
        }
    }
}

function renderStats() {
    document.getElementById('steps').textContent = steps;
    document.getElementById('stars').textContent = starsFound;
}

function renderRecommend() {
    const best = getBestCell();
    const el = document.getElementById('recommend');
    if (!best) {
        el.textContent = '已无未翻格子';
        return;
    }
    const pct = Math.round(best.p * 100);
    el.textContent = `行 ${best.r + 1}, 列 ${best.c + 1} · 概率 ${pct}%`;
}

function refresh() {
    const ok = updateProbabilities();
    renderBoard();
    renderStats();
    renderRecommend();
    if (!ok) showToast('警告：当前约束无合法配置，请检查输入');
    if (starsFound === TOTAL_STARS) {
        showToast(`完成！总共用了 ${steps} 步`);
    }
}

function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    if (msg.startsWith('完成')) {
        setTimeout(() => t.classList.remove('show'), 4000);
    } else {
        setTimeout(() => t.classList.remove('show'), 2500);
    }
}

function hideToast() {
    document.getElementById('toast').classList.remove('show');
}

function onCellClick(r, c) {
    if (starsFound === TOTAL_STARS) return;

    const input = prompt(
        `翻开 (${r + 1}, ${c + 1})：\n` +
        `输入 0-8 = 看到的数字\n` +
        `取消或留空 = 翻到星`,
        ''
    );

    if (input === null || input.trim() === '') {
        revealed.push({ r, c, isStar: true, number: null });
        starsFound++;
        steps++;
        refresh();
        return;
    }

    const num = parseInt(input.trim(), 10);
    if (isNaN(num) || num < 0 || num > 8) {
        alert('请输入 0-8 的数字，或取消表示翻到星');
        return;
    }

    revealed.push({ r, c, isStar: false, number: num });
    steps++;
    refresh();
}

// 初始化
document.getElementById('resetBtn').addEventListener('click', reset);
document.addEventListener('keydown', (e) => {
    if (e.key === 'r' || e.key === 'R') {
        if (confirm('重置当前游戏？')) reset();
    }
});

reset();
