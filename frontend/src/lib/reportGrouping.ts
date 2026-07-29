/**
 * Report grouping/categorization utilities for the daily report page.
 *
 * Pure functions only — no React, no API calls — so the clubbing and
 * categorization logic can be reasoned about (and unit tested later)
 * independently of rendering.
 */
import type { ReportChangeDetail } from "../types";

// ── Category keywords ────────────────────────────────────────────────────
// Matched against the lowercased file path (substring match, first match
// wins, checked in order). Edit this list as new patch/change types come
// up — nothing else needs to change to add a category.
export const DEFAULT_CATEGORY_KEYWORDS: Array<[label: string, keywords: string[]]> = [
  ["kernel", ["kernel", "/modules/", ".build-id", "vmlinuz", "initramfs"]],
  ["grub", ["grub", "/boot/"]],
  ["httpd", ["httpd"]],
  ["apache", ["apachectl", "apache2"]],
  ["conf", [".conf"]],
];

// Extensions whose files always get individual Mtime detail, regardless of
// how large their category is — config file *content* matters more than
// bulk binary/module counts. This is deliberately extension-based, not
// size-based: a 9-file "kernel" category and a 1-file "apache" category
// don't get individual treatment even though they're just as small as the
// 25-file ".conf" category that does, in the real report this was modeled on.
export const DEFAULT_DETAIL_EXTENSIONS = [".conf", ".cfg", ".yaml", ".yml", ".ini", ".json"];

// Similarity floor (0-1) for clubbing two hosts' change sets together.
// Real patch rollouts are rarely byte-identical across hosts (one extra
// local file, timing differences) — this uses similarity rather than
// requiring an exact match.
export const DEFAULT_CLUB_THRESHOLD = 0.9;

const MAX_SAMPLES_PER_BUCKET = 4;
const ROLLUP_MIN_COUNT = 20; // only worth a directory rollup line above this many files

/**
 * Collapse multiple changes for the same (host, file_path) down to just the
 * most recent one, by current_mtime. The same file can legitimately show up
 * more than once in a single day's report — e.g. /etc/shadow changing twice
 * in one day from separate password resets — and every downstream count
 * (bucket totals, "N changes" headers, clubbing similarity) should reflect
 * one logical change per file, not each individual detection.
 */
export function dedupeByLatestMtime(changes: ReportChangeDetail[]): ReportChangeDetail[] {
  const latest = new Map<string, ReportChangeDetail>();
  for (const c of changes) {
    const key = `${c.agent_hostname ?? ""}:${normalizedType(c)}:${c.file_path}`;
    const existing = latest.get(key);
    if (!existing) {
      latest.set(key, c);
      continue;
    }
    const existingTime = existing.current_mtime ? Date.parse(existing.current_mtime) : -Infinity;
    const candidateTime = c.current_mtime ? Date.parse(c.current_mtime) : -Infinity;
    if (candidateTime >= existingTime) latest.set(key, c);
  }
  return Array.from(latest.values());
}

function normalizedType(c: ReportChangeDetail): string {
  return (c.change_type || "").toLowerCase();
}

export function categorizeFile(
  path: string,
  keywords: Array<[string, string[]]> = DEFAULT_CATEGORY_KEYWORDS,
): string {
  const lower = path.toLowerCase();
  for (const [label, kws] of keywords) {
    if (kws.some(kw => lower.includes(kw))) return label;
  }
  return "other";
}

export function isDetailWorthy(
  path: string,
  extensions: string[] = DEFAULT_DETAIL_EXTENSIONS,
): boolean {
  const lower = path.toLowerCase();
  return extensions.some(ext => lower.endsWith(ext));
}

export interface CategoryBucket {
  category: string;
  count: number;
  samples: string[];
  moreCount: number;
}

/** Group changes of one change_type ("added"/"removed"/"changed") into category buckets. */
export function buildBuckets(
  changes: ReportChangeDetail[],
  changeType: string,
  keywords: Array<[string, string[]]> = DEFAULT_CATEGORY_KEYWORDS,
): CategoryBucket[] {
  const relevant = changes.filter(c => normalizedType(c) === changeType);
  const byCategory = new Map<string, ReportChangeDetail[]>();
  for (const c of relevant) {
    const cat = categorizeFile(c.file_path, keywords);
    if (!byCategory.has(cat)) byCategory.set(cat, []);
    byCategory.get(cat)!.push(c);
  }

  const buckets: CategoryBucket[] = [];
  for (const [category, items] of byCategory.entries()) {
    const samples = items.slice(0, MAX_SAMPLES_PER_BUCKET).map(c => c.file_path);
    buckets.push({
      category,
      count: items.length,
      samples,
      moreCount: Math.max(0, items.length - samples.length),
    });
  }

  // Largest first; "other" always sorts last regardless of size, since
  // it's a catch-all rather than a meaningful pattern.
  return buckets.sort((a, b) => {
    if (a.category === "other") return 1;
    if (b.category === "other") return -1;
    return b.count - a.count;
  });
}

export interface DirectoryRollup {
  directory: string;
  count: number;
}

/** Roll up large added/removed subtrees into one line instead of listing every file. */
export function buildDirectoryRollups(
  changes: ReportChangeDetail[],
  changeType: string,
): DirectoryRollup[] {
  const relevant = changes.filter(c => normalizedType(c) === changeType);
  const byDir = new Map<string, number>();
  for (const c of relevant) {
    const idx = c.file_path.lastIndexOf("/");
    const dir = idx > 0 ? c.file_path.slice(0, idx + 1) : "/";
    byDir.set(dir, (byDir.get(dir) || 0) + 1);
  }
  return Array.from(byDir.entries())
    .filter(([, count]) => count >= ROLLUP_MIN_COUNT)
    .map(([directory, count]) => ({ directory, count }))
    .sort((a, b) => b.count - a.count);
}

/** Changed files worth showing individually (see DEFAULT_DETAIL_EXTENSIONS doc above). */
export function buildDetailEntries(
  changes: ReportChangeDetail[],
  extensions: string[] = DEFAULT_DETAIL_EXTENSIONS,
): ReportChangeDetail[] {
  return changes.filter(
    c => normalizedType(c) === "changed"
      && isDetailWorthy(c.file_path, extensions)
      && (c.baseline_mtime || c.current_mtime),
  );
}

// ── Host clubbing ─────────────────────────────────────────────────────────

function changeFingerprint(c: ReportChangeDetail): string {
  // Same file + same change type + same resulting hash = the same actual
  // change, not just coincidentally the same path (e.g. /etc/mtab changes
  // on every host with a different hash each time — that must NOT count
  // as a shared pattern).
  return `${normalizedType(c)}:${c.file_path}:${c.current_hash ?? ""}`;
}

/** Jaccard similarity between two hosts' change sets, by fingerprint. */
export function computeSimilarity(a: ReportChangeDetail[], b: ReportChangeDetail[]): number {
  if (a.length === 0 && b.length === 0) return 1;
  const setA = new Set(a.map(changeFingerprint));
  const setB = new Set(b.map(changeFingerprint));
  let intersection = 0;
  for (const key of setA) if (setB.has(key)) intersection++;
  const union = setA.size + setB.size - intersection;
  return union === 0 ? 1 : intersection / union;
}

export interface HostChanges {
  hostname: string;
  changes: ReportChangeDetail[];
}

export interface HostGroup {
  hostnames: string[];
  changes: ReportChangeDetail[]; // union of every member host's changes, deduped by fingerprint
}

/**
 * Greedy single-pass clustering: each unclubbed host becomes a seed, and
 * any remaining host similar enough to *that seed* joins its group. This
 * compares against the seed only (not the growing merged set) — a
 * deliberate simplification that's more than adequate at the scale of a
 * handful to a few dozen hosts per report, and avoids O(n^2) recompute on
 * a growing set.
 */
export function clubHosts(
  hosts: HostChanges[],
  threshold: number = DEFAULT_CLUB_THRESHOLD,
): { groups: HostGroup[]; solos: HostChanges[] } {
  // Dedupe first — a file detected twice in one day for one host must not
  // inflate that host's change-set size or skew its similarity to others.
  const remaining = hosts.map(h => ({ ...h, changes: dedupeByLatestMtime(h.changes) }));
  const groups: HostGroup[] = [];
  const solos: HostChanges[] = [];

  while (remaining.length > 0) {
    const seed = remaining.shift()!;
    const members = [seed];

    for (let i = remaining.length - 1; i >= 0; i--) {
      const candidate = remaining[i];
      if (computeSimilarity(seed.changes, candidate.changes) >= threshold) {
        members.push(candidate);
        remaining.splice(i, 1);
      }
    }

    if (members.length >= 2) {
      const seen = new Set<string>();
      const merged: ReportChangeDetail[] = [];
      for (const m of members) {
        for (const c of m.changes) {
          const key = changeFingerprint(c);
          if (!seen.has(key)) {
            seen.add(key);
            merged.push(c);
          }
        }
      }
      groups.push({ hostnames: members.map(m => m.hostname), changes: merged });
    } else {
      solos.push(seed);
    }
  }

  return { groups, solos };
}
