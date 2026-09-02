// Every timestamp the API returns is UTC with an explicit offset (see
// app/core/time_utils.py's as_utc). This project's convention is to display
// times in the server's timezone -- IST / Asia/Kolkata, already used
// server-side for report scheduling and generated report/email text (see
// report_scheduler.py's IST constant) -- rather than the viewing browser's
// own local timezone, so the whole team sees the same wall-clock time
// regardless of where they personally are.
const SERVER_TZ = "Asia/Kolkata";

const dateTimeFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: SERVER_TZ,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
  hour12: true,
});

const dateFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: SERVER_TZ,
  year: "numeric",
  month: "numeric",
  day: "numeric",
});

/** e.g. "9/2/2026, 10:27:54 AM IST" */
export function formatServerDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "-";
  return `${dateTimeFormatter.format(d)} IST`;
}

/** e.g. "9/2/2026" */
export function formatServerDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "-";
  return dateFormatter.format(d);
}
