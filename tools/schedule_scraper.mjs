// 스케줄 수집: sen-archive 의 js/schedule_scraper.js 에서 가져온 코드 (엠넷플러스 캘린더 API + 선택적 SECRET_DATA_URL).
// 이 저장소에서는 읽기 전용 스케줄이 필요하므로 이번 달·다음 달만 가져와 out/schedule_data.json 으로 저장한다.
import fs from 'fs';

const FILE_PATH = 'out/schedule_data.json';

async function fetchSecretSourceEvents() {
    const targetUrl = process.env.SECRET_DATA_URL;
    if (!targetUrl) {
        console.error("SECRET_DATA_URL이 비어있습니다. GitHub Secrets 설정을 확인해주세요.");
        return [];
    }

    try {
        console.log("[SECRET_DATA_URL] 데이터를 가져오는 중...");
        const response = await fetch(targetUrl);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const rawData = await response.json();

        if (rawData && Array.isArray(rawData.events)) {
            return rawData.events;
        }
        const currentYear = new Date().getFullYear().toString();
        let filteredDB = {};
        for (const dateKey in rawData) {
            if (dateKey.startsWith(currentYear)) {
                filteredDB[dateKey] = rawData[dateKey];
            }
        }
        const output = Object.keys(filteredDB).length > 0 ? filteredDB : rawData;
        // 옛날 형태({날짜: {...}})는 이벤트 배열로 변환
        return Object.keys(output).map(dateKey => Object.assign({ date: dateKey }, output[dateKey]));
    } catch (error) {
        console.error("[SECRET_DATA_URL] 데이터 가져오기 실패:", error.message);
        return [];
    }
}

const MNET_API_BASE = 'https://artist.mnetplus.world/svc/stg/rescene-official/space/api/v1/calendar';
const MNET_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
const MNET_HEADERS = {
    'User-Agent': MNET_UA,
    'Accept': 'application/json',
    'Referer': 'https://artist.mnetplus.world/'
};

const MNET_LABEL_MAP = {
    '공연': 'concert', '팬사인회': 'fansign', '음방': 'broadcast', '방송': 'broadcast',
    '예능': 'broadcast', '라디오': 'radio', '행사': 'event', '기념일': 'anniv', '공지': 'notice'
};
const MNET_TYPE_KEYWORDS = {
    broadcast: ['음방', '음악방송', 'inkigayo', '인기가요', '뮤직뱅크', 'music bank', 'show champion',
        '엠카운트다운', 'mcountdown', 'the show', '방송', '출연', '인터뷰', 'interview', '예능', '버라이어티', 'variety', '웹예능'],
    radio: ['라디오', 'radio'],
    concert: ['콘서트', 'concert', 'showcase', '쇼케이스', '팬미팅', 'fanmeeting', '공연', '페스티벌', 'festival', 'kcon'],
    fansign: ['팬사인', 'fansign', '사인회', '팬이벤트', '영상통화'],
    event: ['행사', '이벤트', 'event'],
    notice: ['공지', '안내', 'notice'],
    youtube: ['유튜브', 'youtube', '안원잘부', '웹콘텐츠', 'ep.', 'ep ']
};

function mnetClassifyType(ev) {
    const labelName = (ev.label && ev.label.name) || '';
    if (MNET_LABEL_MAP[labelName]) return MNET_LABEL_MAP[labelName];
    const tl = (ev.title || '').toLowerCase();
    for (const type in MNET_TYPE_KEYWORDS) {
        if (MNET_TYPE_KEYWORDS[type].some(kw => tl.includes(kw))) return type;
    }
    return 'notice';
}

function mnetExtractDate(ev) {
    const raw = ev.allDay ? ev.startAtAllDay : (ev.startAt || ev.startAtAllDay || '');
    const m = String(raw || '').match(/(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
}

function mnetExtractTime(ev) {
    if (ev.allDay) return '';
    const m = String(ev.startAt || '').match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!m) return '';
    try {
        const dtUtc = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
        const dtKst = new Date(dtUtc.getTime() + 9 * 60 * 60 * 1000);
        const hh = dtKst.getUTCHours(), mm = dtKst.getUTCMinutes();
        if (hh === 0 && mm === 0) return ''; // 자정(00:00)은 종일 일정으로 취급
        return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
    } catch (e) {
        return '';
    }
}

function mnetBuildParams(year, month) {
    const startKst = new Date(Date.UTC(year, month - 1, 1, 0, 0, 0));
    const startUtc = new Date(startKst.getTime() - 9 * 60 * 60 * 1000);
    const lastDay = new Date(Date.UTC(year, month, 0)); // 해당 달 마지막 날
    const endKst = new Date(Date.UTC(lastDay.getUTCFullYear(), lastDay.getUTCMonth(), lastDay.getUTCDate(), 23, 59, 59));
    const endUtc = new Date(endKst.getTime() - 9 * 60 * 60 * 1000);
    const iso = d => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
    const pad2 = n => String(n).padStart(2, '0');
    return new URLSearchParams({
        startAt: iso(startUtc),
        startAtForAllDay: `${year}-${pad2(month)}-01`,
        endAt: iso(endUtc),
        endAtForAllDay: `${lastDay.getUTCFullYear()}-${pad2(lastDay.getUTCMonth() + 1)}-${pad2(lastDay.getUTCDate())}`
    });
}

async function fetchMnetMonth(year, month) {
    const params = mnetBuildParams(year, month);
    try {
        const res = await fetch(`${MNET_API_BASE}?${params.toString()}`, { headers: MNET_HEADERS });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const events = [];
        for (const ev of (data.events || [])) {
            const d = mnetExtractDate(ev);
            const title = (ev.title || '').trim();
            if (!d || !title) continue;
            const labelName = (ev.label && ev.label.name) || '';
            if (labelName === '기념일') continue; // 기념일은 스케줄이 아니므로 제외
            events.push({
                date: d,
                time: mnetExtractTime(ev),
                title,
                detail: '',
                type: mnetClassifyType(ev),
                source: 'mnetplus'
            });
        }
        console.log(`[MnetPlus] ${year}.${String(month).padStart(2, '0')} → ${events.length}건`);
        return { ok: true, events };
    } catch (e) {
        console.error(`[MnetPlus] ${year}.${String(month).padStart(2, '0')} 조회 실패:`, e.message);
        return { ok: false, events: [] };
    }
}

function monthKey(y, m) { return `${y}-${String(m).padStart(2, '0')}`; }
function nextMonth(y, m) { return m === 12 ? [y + 1, 1] : [y, m + 1]; }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
// 러너(UTC)에 상관없이 한국 시간(KST) 기준 "지금"을 돌려준다 (getUTC* / toISOString 으로 읽을 것)
function kstNow() { return new Date(Date.now() + 9 * 60 * 60 * 1000); }

async function fetchMnetEvents() {
    const today = kstNow();
    const curY = today.getUTCFullYear(), curM = today.getUTCMonth() + 1;
    const [nextY, nextM] = nextMonth(curY, curM);
    let all = [];
    const failedMonths = new Set();
    for (const [yy, mm] of [[curY, curM], [nextY, nextM]]) {
        const { ok, events } = await fetchMnetMonth(yy, mm);
        all = all.concat(events);
        if (!ok) failedMonths.add(monthKey(yy, mm));
        await sleep(250);
    }
    return { events: all, failedMonths };
}

async function main() {
    fs.mkdirSync('out', { recursive: true });
    const secretEvents = process.env.SECRET_DATA_URL ? await fetchSecretSourceEvents() : [];
    const { events: mnetEvents, failedMonths } = await fetchMnetEvents();
    if (failedMonths.size && !mnetEvents.length && !secretEvents.length) throw new Error('조회 실패: ' + [...failedMonths].join(', '));
    const seen = new Set();
    const events = secretEvents.concat(mnetEvents).filter(ev => {
        if (!ev || !ev.date || !ev.title) return false;
        const k = `${ev.date}__${ev.title}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
    }).sort((a, b) => (a.date + (a.time || '')).localeCompare(b.date + (b.time || '')));
    fs.writeFileSync(FILE_PATH, JSON.stringify({ updated: new Date().toISOString(), events }, null, 2), 'utf-8');
    console.log(`✅ 스케줄 ${events.length}건 저장 (${FILE_PATH})`);
}

main().catch(error => {
    console.error('스케줄 가져오기 실패:', error.message);
    process.exitCode = 1;
});
