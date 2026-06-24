function todayNewsDate() {
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const beijing = new Date(utc + 8 * 3600 * 1000);
  if (beijing.getHours() >= 8) {
    beijing.setDate(beijing.getDate() + 1);
  }
  return formatDate(beijing);
}

function formatDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function shiftDate(dateText, delta) {
  const parts = String(dateText).split('-').map(Number);
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  date.setDate(date.getDate() + delta);
  return formatDate(date);
}

module.exports = {
  todayNewsDate,
  shiftDate
};
