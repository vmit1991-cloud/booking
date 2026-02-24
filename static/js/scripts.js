const WORK_START_MIN = 8 * 60;
const WORK_END_MIN = 20 * 60;
const WORK_TOTAL_MIN = WORK_END_MIN - WORK_START_MIN;

let _roomsCache = [];
let _bookings = [];
let _lastBookingsById = new Map();

let viewMode = "day";
let _selectedDayForModal = null;
let _fp = null;
let _curAnchor = new Date();
let _suppressOpen = false;

function pad2(n){ return String(n).padStart(2,"0"); }

function parseHHMM(s){
  const [h,m] = (s || "").split(":").map(x => parseInt(x,10));
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return {h, m};
}

function hhmmFromMinutes(min){
  const h = Math.floor(min/60);
  const m = min % 60;
  return `${pad2(h)}:${pad2(m)}`;
}

function escapeHtml(str){
  return (str || "").replace(/[&<>"']/g, (c) => ({
    "&":"&amp;",
    "<":"&lt;",
    ">":"&gt;",
    '"':"&quot;",
    "'":"&#039;"
  }[c]));
}

function getCookie(name){
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return "";
}

function toast(msg){
  if (window.M && M.toast){ M.toast({ html: msg }); return; }
  alert(msg);
}

function clampToWork(min){
  return Math.max(WORK_START_MIN, Math.min(WORK_END_MIN, min));
}

function pct(min){
  const c = clampToWork(min);
  return ((c - WORK_START_MIN) / WORK_TOTAL_MIN) * 100;
}

function parseDMY(s){
  const p = (s || "").split(".");
  if (p.length !== 3) return null;
  const dd = parseInt(p[0],10);
  const mm = parseInt(p[1],10) - 1;
  const yy = parseInt(p[2],10);
  if ([dd,mm,yy].some(Number.isNaN)) return null;
  return new Date(yy, mm, dd, 0, 0, 0, 0);
}

function formatDMY(d){
  return `${pad2(d.getDate())}.${pad2(d.getMonth()+1)}.${d.getFullYear()}`;
}

function startOfWeekMonday(d){
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0,0,0,0);
  const day = (x.getDay() + 6) % 7;
  x.setDate(x.getDate() - day);
  return x;
}

function addDays(d, n){
  const x = new Date(d.getTime());
  x.setDate(x.getDate() + n);
  return x;
}

function uaMonthName(m){
  return [
    "січня","лютого","березня","квітня","травня","червня",
    "липня","серпня","вересня","жовтня","листопада","грудня"
  ][m];
}

function formatDayLabelUA(d){
  return `${d.getDate()} ${uaMonthName(d.getMonth())} ${d.getFullYear()} р.`;
}

function formatWeekLabelUA(anchor){
  const ws = startOfWeekMonday(anchor);
  const we = addDays(ws, 6);
  const left = `${ws.getDate()} ${uaMonthName(ws.getMonth())}`;
  const right = `${we.getDate()} ${uaMonthName(we.getMonth())}`;
  if (ws.getFullYear() === we.getFullYear()){
    return `${left} — ${right} ${ws.getFullYear()} р.`;
  }
  return `${left} ${ws.getFullYear()} — ${right} ${we.getFullYear()}`;
}

function dayRangeISO(dayDate){
  const s = new Date(dayDate.getFullYear(), dayDate.getMonth(), dayDate.getDate(), 0,0,0);
  const e = new Date(dayDate.getFullYear(), dayDate.getMonth(), dayDate.getDate(), 23,59,59);
  return { startISO: s.toISOString(), endISO: e.toISOString() };
}

function weekRangeISO(weekStart){
  const start = new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate(), 0,0,0);
  const end = new Date(weekStart.getFullYear(), weekStart.getMonth(), weekStart.getDate()+6, 23,59,59);
  return { startISO: start.toISOString(), endISO: end.toISOString() };
}

function toLocalDateFromDayHHMM(dayDate, hhmm){
  const t = parseHHMM(hhmm);
  if (!t) return null;
  return new Date(dayDate.getFullYear(), dayDate.getMonth(), dayDate.getDate(), t.h, t.m, 0, 0);
}

function toISOFromDayHHMM(dayDate, hhmm){
  const d = toLocalDateFromDayHHMM(dayDate, hhmm);
  return d ? d.toISOString() : null;
}

function isSameLocalDay(a, b){
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function nowRoundedUpToStep(stepMin){
  const now = new Date();
  const m = now.getMinutes();
  const rounded = Math.ceil(m / stepMin) * stepMin;
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours(), 0, 0, 0);
  d.setMinutes(rounded);
  return d;
}

function minutesFromLocalDate(d){
  return d.getHours() * 60 + d.getMinutes();
}

function suggestStartMinForDay(dayDate, fallbackMin){
  const now = new Date();
  if (!isSameLocalDay(dayDate, now)) return fallbackMin;
  const rounded = nowRoundedUpToStep(5);
  const m = minutesFromLocalDate(rounded);
  return clampToWork(Math.max(fallbackMin, m));
}

function setAdv(open){
  const advBtn = document.getElementById("advBtn");
  const advBody = document.getElementById("advBody");
  const advIc = document.getElementById("advIc");
  advBody.classList.toggle("open", open);
  advBody.setAttribute("aria-hidden", open ? "false" : "true");
  advBtn.setAttribute("aria-expanded", open ? "true" : "false");
  advIc.textContent = open ? "expand_less" : "expand_more";
}

function getSelectedRoomIds(){
  const boxes = Array.from(document.querySelectorAll('input[name="roomFilter"]:checked'));
  if (!boxes.length) return null;
  return new Set(boxes.map(b => String(b.value)));
}

function applyRoomFilters(rooms){
  const selectedIds = getSelectedRoomIds();
  const capMin = parseInt(document.getElementById("minSeats").value || "0", 10) || 0;
  const needProjector = document.getElementById("eqProjector").checked;
  const needMic = document.getElementById("eqMic").checked;
  const needTV = document.getElementById("eqTv").checked;
  const needBoard = document.getElementById("eqBoard").checked;

  return rooms.filter(r => {
    if (selectedIds && !selectedIds.has(String(r.id))) return false;
    if ((r.capacity || 0) < capMin) return false;
    if (needProjector && !r.has_projector) return false;
    if (needMic && !r.has_speakerphone) return false;
    if (needTV && !r.has_tv) return false;
    if (needBoard && !r.has_whiteboard) return false;
    return true;
  });
}

function setSelectOptions(selectEl, options, selectedId, placeholderText){
  selectEl.innerHTML = "";
  if (placeholderText){
    const ph = document.createElement("option");
    ph.value = "";
    ph.textContent = placeholderText;
    ph.disabled = true;
    ph.selected = true;
    selectEl.appendChild(ph);
  }
  for (const r of options){
    const opt = document.createElement("option");
    opt.value = String(r.id);
    opt.textContent = r.name;
    if (selectedId && String(r.id) === String(selectedId)) opt.selected = true;
    selectEl.appendChild(opt);
  }
}

function renderRoomsList(rooms){
  const host = document.getElementById("roomsList");
  host.innerHTML = "";
  if (!rooms || !rooms.length){
    host.innerHTML = `<div class="rooms-hint">Немає переговорних.</div>`;
    return;
  }
  for (const r of rooms){
    const lbl = document.createElement("label");
    lbl.className = "room-item";
    lbl.innerHTML = `<input type="checkbox" name="roomFilter" value="${escapeHtml(String(r.id))}"><span class="room-name">${escapeHtml(r.name)}</span>`;
    host.appendChild(lbl);
  }
}

async function preloadRooms(){
  const rooms = await fetch("/api/rooms/").then(r => r.json());
  _roomsCache = rooms;
  setSelectOptions(document.getElementById("modalRoomSelect"), rooms, null, "Оберіть переговорну");
  renderRoomsList(rooms);
}

async function loadBookings(rangeStartISO, rangeEndISO){
  const bookings = await fetch(`/api/bookings/?start=${encodeURIComponent(rangeStartISO)}&end=${encodeURIComponent(rangeEndISO)}`).then(r => r.json());
  _bookings = [];
  _lastBookingsById = new Map();
  for (const b of bookings){
    const roomId = b.extendedProps?.roomId ?? b.roomId ?? b.room_id;
    if (!roomId) continue;
    const id = b.id ?? b.extendedProps?.id ?? null;
    const startMs = new Date(b.start).getTime();
    const endMs = new Date(b.end).getTime();
    const bk = {
      id,
      roomId,
      startMs,
      endMs,
      title: b.title || "",
      bookedBy: b.extendedProps?.bookedBy || b.bookedBy || "",
      canCancel: !!(b.extendedProps?.canCancel ?? b.canCancel ?? b.extendedProps?.isOwner ?? b.isOwner),
    };
    _bookings.push(bk);
    if (id) _lastBookingsById.set(String(id), bk);
  }
}

const overlayEl = () => document.getElementById("bookingOverlay");
const modalEl = () => document.getElementById("bookingModal");

function openModal(){
  overlayEl().style.display = "block";
  modalEl().style.display = "block";
  modalEl().setAttribute("aria-hidden","false");
  document.body.style.overflow = "hidden";
}

function closeModal(){
  overlayEl().style.display = "none";
  modalEl().style.display = "none";
  modalEl().setAttribute("aria-hidden","true");
  document.body.style.overflow = "";
}

const viewOverlayEl = () => document.getElementById("viewOverlay");
const viewModalEl = () => document.getElementById("viewModal");

function openViewModal(){
  viewOverlayEl().style.display = "block";
  viewModalEl().style.display = "block";
  viewModalEl().setAttribute("aria-hidden","false");
  document.body.style.overflow = "hidden";
}

function closeViewModal(){
  viewOverlayEl().style.display = "none";
  viewModalEl().style.display = "none";
  viewModalEl().setAttribute("aria-hidden","true");
  document.body.style.overflow = "";
  const btn = document.getElementById("cancelEventBtn");
  btn.style.display = "none";
  btn.dataset.bookingId = "";
}

function openBookingModal({ roomId, startMin, durationMin, dayDateOverride }){
  const dayDate = dayDateOverride || (viewMode === "week" ? _selectedDayForModal : parseDMY(document.getElementById("dateInput").value));
  const safeStartMin = dayDate ? suggestStartMinForDay(dayDate, startMin) : startMin;

  const start = hhmmFromMinutes(safeStartMin);
  let endMin = safeStartMin + durationMin;
  if (endMin > WORK_END_MIN) endMin = WORK_END_MIN;
  const end = hhmmFromMinutes(endMin);

  if (roomId){
    setSelectOptions(document.getElementById("modalRoomSelect"), _roomsCache, roomId, null);
  } else {
    setSelectOptions(document.getElementById("modalRoomSelect"), _roomsCache, null, "Оберіть переговорну");
  }

  document.getElementById("modalStart").value = start;
  document.getElementById("modalEnd").value = end;
  document.getElementById("modalTitle").value = "";
  openModal();
}

function showBookingDetails(booking){
  const title = booking.title ? booking.title : "Без назви";
  const st = new Date(booking.startMs);
  const en = new Date(booking.endMs);
  const time = `${pad2(st.getDate())}.${pad2(st.getMonth()+1)} ${pad2(st.getHours())}:${pad2(st.getMinutes())}–${pad2(en.getHours())}:${pad2(en.getMinutes())}`;
  document.getElementById("vTitle").textContent = title;
  document.getElementById("vTime").textContent = time;
  document.getElementById("vBy").textContent = booking.bookedBy || "—";
  const btn = document.getElementById("cancelEventBtn");
  if (booking.canCancel && booking.id){
    btn.style.display = "inline-flex";
    btn.dataset.bookingId = String(booking.id);
  } else {
    btn.style.display = "none";
    btn.dataset.bookingId = "";
  }
  openViewModal();
}

function validateNotPast(startLocal, endLocal){
  if (!startLocal || !endLocal) return { ok:false, msg:"Заповни час" };
  if (endLocal <= startLocal) return { ok:false, msg:"Кінець має бути пізніше за початок" };
  const now = new Date();
  if (startLocal < now) return { ok:false, msg:"Не можна створювати бронювання в минулому" };
  return { ok:true };
}

async function createBookingFromModal(){
  const roomRaw = document.getElementById("modalRoomSelect").value;
  const roomId = parseInt(roomRaw, 10);
  if (!roomRaw || Number.isNaN(roomId)){ toast("Оберіть переговорну"); return; }

  const st = document.getElementById("modalStart").value;
  const en = document.getElementById("modalEnd").value;

  let dayDate = null;
  if (viewMode === "week"){
    dayDate = _selectedDayForModal;
    if (!dayDate){ toast("Не вибраний день"); return; }
  } else {
    dayDate = parseDMY(document.getElementById("dateInput").value);
    if (!dayDate){ toast("Невірна дата"); return; }
  }

  const startLocal = toLocalDateFromDayHHMM(dayDate, st);
  const endLocal = toLocalDateFromDayHHMM(dayDate, en);

  const v = validateNotPast(startLocal, endLocal);
  if (!v.ok){ toast(v.msg); return; }

  const payload = {
    room_id: roomId,
    start: startLocal.toISOString(),
    end: endLocal.toISOString(),
    title: (document.getElementById("modalTitle").value || "").trim(),
  };

  try {
    const res = await fetch("/api/bookings/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCookie("csrftoken"),
      },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok){ toast(data.error || "Помилка"); return; }
    closeModal();
    await loadAndRender();
    toast("Створено");
  } catch (e){
    console.error(e);
    toast("Помилка запиту");
  }
}

async function cancelBookingById(id){
  try{
    const res = await fetch(`/api/bookings/${encodeURIComponent(id)}/cancel/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false){
      toast(data.error || "Не вдалося скасувати");
      return;
    }
    closeViewModal();
    await loadAndRender();
    toast("Скасовано");
  } catch(e){
    console.error(e);
    toast("Помилка запиту");
  }
}

function renderScaleHeader(){
  const el = document.getElementById("scaleHeader");
  el.innerHTML = "";
  for (let h = 8; h <= 20; h++){
    const d = document.createElement("div");
    d.className = "hour";
    d.textContent = String(h).padStart(2,"0");
    el.appendChild(d);
  }
}

function eqIcon(on, iconName, title){
  const cls = on ? "eq-ic on" : "eq-ic off";
  return `<div class="${cls}" title="${escapeHtml(title)}"><i class="material-icons" style="font-size:18px;">${iconName}</i></div>`;
}

async function renderDay(){
  const dayDate = parseDMY(document.getElementById("dateInput").value);
  if (!dayDate){ toast("Невірна дата"); return; }
  const range = dayRangeISO(dayDate);
  const occBody = document.getElementById("occBody");
  occBody.innerHTML = `<div class="grey-text" style="padding: 12px;">Завантаження...</div>`;
  try{
    await loadBookings(range.startISO, range.endISO);
    const byRoom = new Map();
    for (const bk of _bookings){
      if (!byRoom.has(bk.roomId)) byRoom.set(bk.roomId, []);
      byRoom.get(bk.roomId).push(bk);
    }
    const roomsFiltered = applyRoomFilters(_roomsCache);
    occBody.innerHTML = "";
    if (!roomsFiltered.length){
      occBody.innerHTML = `<div class="grey-text" style="padding: 12px;">Немає переговорних під фільтри.</div>`;
      return;
    }
    const durationMin = 60;
    for (const r of roomsFiltered){
      const row = document.createElement("div");
      row.className = "occ-row";

      const cRoom = document.createElement("div");
      cRoom.innerHTML = `<div class="room-name">${escapeHtml(r.name)}</div><div class="room-meta">${r.capacity || 0} місць</div>`;

      const cEq = document.createElement("div");
      cEq.innerHTML = `<div class="eq-icons">${eqIcon(!!r.has_projector, "cast", "Проектор")}${eqIcon(!!r.has_speakerphone, "mic", "Спікерфон")}${eqIcon(!!r.has_tv, "tv", "Телевізор")}${eqIcon(!!r.has_whiteboard, "border_color", "Маркерна дошка")}</div>`;

      const cScale = document.createElement("div");
      const bar = document.createElement("div");
      bar.className = "scale-bar free-hover";

      bar.addEventListener("click", (e) => {
        if (e.target && e.target.closest(".busy-seg")) return;

        const rect = bar.getBoundingClientRect();
        const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
        const ratio = rect.width ? (x / rect.width) : 0;

        const minute = WORK_START_MIN + Math.round((ratio * WORK_TOTAL_MIN) / 5) * 5;
        const startMin = clampToWork(minute);
        openBookingModal({ roomId: r.id, startMin, durationMin, dayDateOverride: dayDate });
      });

      const roomBookings = (byRoom.get(r.id) || []).slice().sort((a,b) => a.startMs - b.startMs);
      for (const bk of roomBookings){
        const st = new Date(bk.startMs);
        const en = new Date(bk.endMs);
        const stMin = st.getHours()*60 + st.getMinutes();
        const enMin = en.getHours()*60 + en.getMinutes();
        const leftPct = pct(stMin);
        const rightPct = pct(enMin);
        const widthPct = Math.max(0.5, rightPct - leftPct);

        const seg = document.createElement("div");
        seg.className = "busy-seg";
        seg.style.left = `${leftPct}%`;
        seg.style.width = `${widthPct}%`;
        seg.title = `${bk.title ? bk.title : "Бронювання"} (${pad2(st.getHours())}:${pad2(st.getMinutes())}–${pad2(en.getHours())}:${pad2(en.getMinutes())})`;
        seg.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          showBookingDetails(bk);
        });
        bar.appendChild(seg);
      }

      cScale.appendChild(bar);
      row.appendChild(cRoom);
      row.appendChild(cEq);
      row.appendChild(cScale);
      occBody.appendChild(row);
    }
  } catch(e){
    console.error(e);
    occBody.innerHTML = `<div class="red-text" style="padding: 12px;">Помилка завантаження даних.</div>`;
  }
}

function buildWeekDays(weekStart){
  const uaNames = ["Пн","Вт","Ср","Чт","Пт","Сб","Нд"];
  const days = [];
  for (let i=0;i<7;i++){
    const d = addDays(weekStart, i);
    days.push({ d, label: uaNames[i], short: `${pad2(d.getDate())}.${pad2(d.getMonth()+1)}` });
  }
  return days;
}

function renderDaysHeader(days){
  const el = document.getElementById("daysHeader");
  const elHours = document.getElementById("daysHours");
  el.innerHTML = "";
  elHours.innerHTML = "";
  for (const item of days){
    const box = document.createElement("div");
    box.className = "day-head";
    box.innerHTML = `<div class="d-name">${item.label}</div><div class="d-date">${item.short}</div>`;
    el.appendChild(box);
    const h = document.createElement("div");
    h.className = "hours-cell";
    h.innerHTML = `<span>08:00</span><span>20:00</span>`;
    elHours.appendChild(h);
  }
}

function bookingsForRoomAndDay(roomId, dayDate){
  const r = dayRangeISO(dayDate);
  const s = new Date(r.startISO).getTime();
  const e = new Date(r.endISO).getTime();
  return _bookings
    .filter(x => x.roomId === roomId && x.endMs >= s && x.startMs <= e)
    .sort((a,b) => a.startMs - b.startMs);
}

async function renderWeek(){
  const anchor = parseDMY(document.getElementById("dateInput").value);
  if (!anchor){ toast("Невірна дата"); return; }

  const weekStart = startOfWeekMonday(anchor);
  const range = weekRangeISO(weekStart);
  const days = buildWeekDays(weekStart);
  renderDaysHeader(days);

  const body = document.getElementById("wkBody");
  body.innerHTML = `<div class="grey-text" style="padding: 12px;">Завантаження...</div>`;

  try{
    await loadBookings(range.startISO, range.endISO);
    const roomsFiltered = applyRoomFilters(_roomsCache);
    body.innerHTML = "";

    if (!roomsFiltered.length){
      body.innerHTML = `<div class="grey-text" style="padding: 12px;">Немає переговорних під фільтри.</div>`;
      return;
    }

    const durationMin = 60;

    for (const r of roomsFiltered){
      const row = document.createElement("div");
      row.className = "wk-row";

      const roomCell = document.createElement("div");
      roomCell.className = "room-cell";
      roomCell.innerHTML = `<div class="room-name">${escapeHtml(r.name)}</div><div class="room-meta">${r.capacity || 0} місць</div>`;

      const daysCell = document.createElement("div");
      daysCell.className = "days-grid";

      for (const dayObj of days){
        const dayCell = document.createElement("div");
        dayCell.className = "day-cell";

        const scale = document.createElement("div");
        scale.className = "wk-scale";

        scale.addEventListener("click", (e) => {
          if (e.target && e.target.closest(".wk-seg")) return;

          const rect = scale.getBoundingClientRect();
          const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
          const ratio = rect.width ? (x / rect.width) : 0;

          const minute = WORK_START_MIN + Math.round((ratio * WORK_TOTAL_MIN) / 5) * 5;
          const startMin = clampToWork(minute);

          _selectedDayForModal = dayObj.d;
          openBookingModal({ roomId: r.id, startMin, durationMin, dayDateOverride: dayObj.d });
        });

        const bks = bookingsForRoomAndDay(r.id, dayObj.d);
        for (const bk of bks){
          const st = new Date(bk.startMs);
          const en = new Date(bk.endMs);
          const stMin = st.getHours()*60 + st.getMinutes();
          const enMin = en.getHours()*60 + en.getMinutes();
          const leftPct = pct(stMin);
          const rightPct = pct(enMin);
          const widthPct = Math.max(0.5, rightPct - leftPct);

          const seg = document.createElement("div");
          seg.className = "wk-seg";
          seg.style.left = `${leftPct}%`;
          seg.style.width = `${widthPct}%`;
          seg.title = `${bk.title ? bk.title : "Бронювання"} (${pad2(st.getHours())}:${pad2(st.getMinutes())}–${pad2(en.getHours())}:${pad2(en.getMinutes())})`;
          seg.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            showBookingDetails(bk);
          });

          scale.appendChild(seg);
        }

        dayCell.appendChild(scale);
        daysCell.appendChild(dayCell);
      }

      row.appendChild(roomCell);
      row.appendChild(daysCell);
      body.appendChild(row);
    }
  } catch(e){
    console.error(e);
    body.innerHTML = `<div class="red-text" style="padding: 12px;">Помилка завантаження даних.</div>`;
  }
}

function syncDateLabel(){
  const d = parseDMY(document.getElementById("dateInput").value) || _curAnchor;
  document.getElementById("dateLabel").textContent = (viewMode === "week")
    ? formatWeekLabelUA(d)
    : formatDayLabelUA(d);
}

function setMode(mode){
  viewMode = mode;

  const isDay = mode === "day";
  document.getElementById("dayView").style.display = isDay ? "block" : "none";
  document.getElementById("weekView").style.display = isDay ? "none" : "block";

  const btnDay = document.getElementById("btnDay");
  const btnWeek = document.getElementById("btnWeek");

  btnDay.classList.toggle("is-active", isDay);
  btnWeek.classList.toggle("is-active", !isDay);

  btnDay.setAttribute("aria-selected", isDay ? "true" : "false");
  btnWeek.setAttribute("aria-selected", !isDay ? "true" : "false");

  document.getElementById("pageTitle").textContent = isDay ? "Переговорні на день" : "Переговорні на тиждень";
  document.getElementById("pageSubtitle").textContent = "";

  syncDateLabel();
  loadAndRender();
}

function debounce(fn, ms=200){
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

const scheduleRender = debounce(() => loadAndRender(), 200);

async function loadAndRender(){
  syncDateLabel();
  if (viewMode === "week") return renderWeek();
  return renderDay();
}

function setAnchorDate(d){
  _curAnchor = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0,0,0,0);
  const v = formatDMY(_curAnchor);
  document.getElementById("dateInput").value = v;
  if (_fp) _fp.setDate(v, false, "d.m.Y");
  syncDateLabel();
}

document.addEventListener("DOMContentLoaded", async () => {
  const dateInput = document.getElementById("dateInput");

  _fp = flatpickr(dateInput, {
    locale: flatpickr.l10ns.uk,
    dateFormat: "d.m.Y",
    allowInput: true,
    clickOpens: false,
    disableMobile: true,
    monthSelectorType: "static",
    prevArrow: "‹",
    nextArrow: "›",
    onOpen: (sel, str, inst) => {
      if (_suppressOpen) inst.close();
    },
    onChange: (sel) => {
      if (sel && sel[0]) {
        setAnchorDate(sel[0]);
        scheduleRender();
      }
    }
  });

  setAnchorDate(new Date());

  const dateBtn = document.getElementById("dateBtn");
  dateBtn.addEventListener("mousedown", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });

  dateBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!_fp) return;
    if (_fp.isOpen) {
      _suppressOpen = true;
      _fp.close();
      try { document.activeElement && document.activeElement.blur && document.activeElement.blur(); } catch(err){}
      setTimeout(() => { _suppressOpen = false; }, 0);
    } else {
      _fp.open();
    }
  });

  document.getElementById("prevBtn").addEventListener("click", () => {
    const step = (viewMode === "week") ? -7 : -1;
    setAnchorDate(addDays(_curAnchor, step));
    loadAndRender();
  });

  document.getElementById("nextBtn").addEventListener("click", () => {
    const step = (viewMode === "week") ? 7 : 1;
    setAnchorDate(addDays(_curAnchor, step));
    loadAndRender();
  });

  const pop = document.getElementById("filterPop");
  const btn = document.getElementById("filterBtn");
  const closeBtn = document.getElementById("filterCloseBtn");

  function closePop(){
    pop.classList.remove("open");
    pop.setAttribute("aria-hidden","true");
    setAdv(false);
  }

  function openPop(){
    pop.classList.add("open");
    pop.setAttribute("aria-hidden","false");
  }

  function togglePop(){
    if (pop.classList.contains("open")) closePop();
    else openPop();
  }

  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    togglePop();
  });

  closeBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    closePop();
  });

  document.addEventListener("click", (e) => {
    if (!pop.contains(e.target) && !btn.contains(e.target)) closePop();
  });

  document.getElementById("advBtn").addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const advBody = document.getElementById("advBody");
    setAdv(!advBody.classList.contains("open"));
  });

  document.getElementById("roomsClear").addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelectorAll('input[name="roomFilter"]').forEach(x => x.checked = false);
    const seats = document.getElementById("minSeats");
    if (seats) seats.value = "";
    ["eqProjector","eqMic","eqTv","eqBoard"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.checked = false;
    });
    scheduleRender();
  });

  document.getElementById("roomsList").addEventListener("change", (e) => {
    const t = e.target;
    if (t && t.matches('input[name="roomFilter"]')) scheduleRender();
  });

  document.getElementById("minSeats").addEventListener("input", scheduleRender);
  ["eqProjector","eqMic","eqTv","eqBoard"].forEach(id => {
    document.getElementById(id).addEventListener("change", scheduleRender);
  });

  document.getElementById("applyFilters").addEventListener("click", (e) => {
    e.preventDefault();
    closePop();
    loadAndRender();
  });

  document.getElementById("btnDay").addEventListener("click", () => setMode("day"));
  document.getElementById("btnWeek").addEventListener("click", () => setMode("week"));

  document.getElementById("openNewBookingBtn").addEventListener("click", () => {
    const durationMin = 60;
    if (!_roomsCache?.length){ toast("Немає переговорних"); return; }

    if (viewMode === "week"){
      const anchor = parseDMY(dateInput.value) || _curAnchor;
      const ws = startOfWeekMonday(anchor);
      _selectedDayForModal = addDays(ws, 0);
    } else {
      _selectedDayForModal = null;
    }

    const dayDate = (viewMode === "week") ? _selectedDayForModal : parseDMY(document.getElementById("dateInput").value);
    const startMin = dayDate ? suggestStartMinForDay(dayDate, WORK_START_MIN) : WORK_START_MIN;

    openBookingModal({
      roomId: null,
      startMin,
      durationMin,
      dayDateOverride: dayDate || null
    });
  });

  document.getElementById("createBookingBtn").addEventListener("click", createBookingFromModal);
  document.getElementById("cancelBookingBtn").addEventListener("click", closeModal);
  document.getElementById("closeXBtn").addEventListener("click", closeModal);
  document.getElementById("bookingOverlay").addEventListener("click", closeModal);

  document.getElementById("closeViewBtn").addEventListener("click", closeViewModal);
  document.getElementById("closeViewXBtn").addEventListener("click", closeViewModal);
  document.getElementById("viewOverlay").addEventListener("click", closeViewModal);
  document.getElementById("cancelEventBtn").addEventListener("click", (e) => {
    const id = e.currentTarget.dataset.bookingId;
    if (!id) return;
    cancelBookingById(id);
  });

  function openTimePicker(inputEl){
    if (!inputEl) return;
    if (typeof inputEl.showPicker === "function") {
      try { inputEl.showPicker(); return; } catch (e) {}
    }
    inputEl.focus({ preventScroll: true });
    inputEl.click();
  }

  document.querySelectorAll(".js-open-time").forEach(ic => {
    ic.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const id = ic.getAttribute("data-target");
      openTimePicker(document.getElementById(id));
    });
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (_fp && _fp.isOpen) _fp.close();
      closePop();
      if (modalEl().style.display === "block") closeModal();
      if (viewModalEl().style.display === "block") closeViewModal();
    }
  });

  renderScaleHeader();
  await preloadRooms();
  setAdv(false);
  setMode("day");
});