// The front-office staff, drawn with the "Personas" avatar style by Draftbit
// (CC BY 4.0, https://www.draftbit.com), generated locally by DiceBear (MIT).
import { createAvatar } from "@dicebear/core";
import * as personas from "@dicebear/personas";

export const CREDIT = {
  text: "Characters: “Personas” by Draftbit, CC BY 4.0, via DiceBear",
  url: "https://www.dicebear.com/styles/personas/",
};

// One look per agent; shirt colors match each agent's color in the hub.
const LOOKS = {
  showrunner: { hair: "shortCombover", hairColor: "b9bec4", skinColor: "e5a07e", clothingColor: "2b3240", body: "squared", eyes: "open", mouth: "smirk", facialHair: "shadow" },
  research: { hair: "cap", hairColor: "1b4b5c", skinColor: "b16a5b", clothingColor: "4cc9f0", body: "rounded", eyes: "open", mouth: "smile" },
  script: { hair: "curlyBun", hairColor: "6c4545", skinColor: "eeb4a4", clothingColor: "b794ff", body: "rounded", eyes: "glasses", mouth: "smile" },
  qa: { hair: "buzzcut", hairColor: "362c47", skinColor: "92594b", clothingColor: "f4f1ea", body: "checkered", eyes: "open", mouth: "smirk" },
  studio: { hair: "curlyHighTop", hairColor: "362c47", skinColor: "623d36", clothingColor: "3ddc84", body: "squared", eyes: "happy", mouth: "smile" },
  packaging: { hair: "bobBangs", hairColor: "e15c66", skinColor: "d78774", clothingColor: "ff8a3d", body: "rounded", eyes: "open", mouth: "bigSmile" },
  publisher: { hair: "fade", hairColor: "dee1f5", skinColor: "eeb4a4", clothingColor: "6b9bff", body: "small", eyes: "glasses", mouth: "smile", facialHair: "goatee" },
};

const cache = new Map();

// The face follows the agent's state: dozing on a break, a frown when blocked.
export function avatarUri(name, status) {
  const look = LOOKS[name];
  if (!look) return null;
  const key = `${name}:${status}`;
  if (cache.has(key)) return cache.get(key);
  const eyes = status === "paused" || status === "waiting" ? "sleep" : look.eyes;
  const mouth = status === "blocked" || status === "error" ? "frown" : status === "working" ? (look.mouth === "smirk" ? "smile" : look.mouth) : look.mouth;
  const uri = createAvatar(personas, {
    seed: name,
    hair: [look.hair],
    hairColor: [look.hairColor],
    skinColor: [look.skinColor],
    clothingColor: [look.clothingColor],
    body: [look.body],
    eyes: [eyes],
    mouth: [mouth],
    nose: ["smallRound"],
    facialHair: look.facialHair ? [look.facialHair] : [],
    facialHairProbability: look.facialHair ? 100 : 0,
  }).toDataUri();
  cache.set(key, uri);
  return uri;
}

// The Game Day Brain studio's staff are robots, drawn here (original art, no credit needed). Same agent colors as the Archive's staff.
const ROBOTS = {
  showrunner: { head: "square", eyes: "visor", antenna: "double", trim: "2b3240" },
  research: { head: "dome", eyes: "lens", antenna: "dish", trim: "4cc9f0" },
  script: { head: "round", eyes: "glasses", antenna: "spring", trim: "b794ff" },
  qa: { head: "square", eyes: "cyclops", antenna: "siren", trim: "f4f1ea" },
  studio: { head: "tv", eyes: "screen", antenna: "ears", trim: "3ddc84" },
  packaging: { head: "round", eyes: "round", antenna: "bulb", trim: "ff8a3d" },
  publisher: { head: "tall", eyes: "visor", antenna: "single", trim: "6b9bff" },
};

const METAL = "#c9d1da";
const DARK = "#2a3140";
const INK = "#141821";

function robotEyes(kind, mood, glow) {
  if (mood === "sleep") return `<path d="M36 47h10M54 47h10" stroke="${INK}" stroke-width="3" stroke-linecap="round"/>`;
  if (mood === "alarm") return `<path d="M35 42l10 10M45 42l-10 10M55 42l10 10M65 42l-10 10" stroke="#ff5470" stroke-width="3.5" stroke-linecap="round"/>`;
  switch (kind) {
    case "visor": return `<rect x="30" y="40" width="40" height="13" rx="6.5" fill="${INK}"/><rect x="34" y="44" width="32" height="5" rx="2.5" fill="${glow}"/>`;
    case "cyclops": return `<circle cx="50" cy="47" r="10" fill="${INK}"/><circle cx="50" cy="47" r="5.5" fill="${glow}"/>`;
    case "lens": return `<circle cx="40" cy="47" r="7" fill="${INK}"/><circle cx="40" cy="47" r="3.5" fill="${glow}"/><circle cx="61" cy="46" r="10" fill="${INK}" stroke="${DARK}" stroke-width="2"/><circle cx="61" cy="46" r="5" fill="${glow}"/>`;
    case "glasses": return `<circle cx="40" cy="47" r="8" fill="none" stroke="${INK}" stroke-width="2.5"/><circle cx="60" cy="47" r="8" fill="none" stroke="${INK}" stroke-width="2.5"/><path d="M48 47h4" stroke="${INK}" stroke-width="2.5"/><circle cx="40" cy="47" r="3.5" fill="${glow}"/><circle cx="60" cy="47" r="3.5" fill="${glow}"/>`;
    case "screen": return `<rect x="31" y="37" width="38" height="24" rx="4" fill="${INK}"/><circle cx="42" cy="47" r="3.5" fill="${glow}"/><circle cx="58" cy="47" r="3.5" fill="${glow}"/>`;
    default: return `<circle cx="40" cy="47" r="6.5" fill="${INK}"/><circle cx="60" cy="47" r="6.5" fill="${INK}"/><circle cx="41.5" cy="45.5" r="2.5" fill="${glow}"/><circle cx="61.5" cy="45.5" r="2.5" fill="${glow}"/>`;
  }
}

function robotMouth(mood, head) {
  const y = head === "tv" ? 57 : 58;
  if (mood === "alarm") return `<path d="M40 ${y + 2} l4 -3 l4 3 l4 -3 l4 3 l4 -3" stroke="${INK}" stroke-width="2.5" fill="none" stroke-linejoin="round"/>`;
  if (mood === "sleep") return `<rect x="43" y="${y}" width="14" height="3" rx="1.5" fill="${INK}"/>`;
  const smile = mood === "happy";
  return `<rect x="40" y="${y - 2}" width="20" height="${smile ? 7 : 5}" rx="${smile ? 3.5 : 2}" fill="${INK}"/>` +
    [44, 48, 52, 56].map((x) => `<rect x="${x}" y="${y - 1}" width="1.6" height="${smile ? 5 : 3}" fill="${METAL}"/>`).join("");
}

function robotHead(kind, trim) {
  switch (kind) {
    case "dome": return `<path d="M24 64V46a26 26 0 0 1 52 0v18z" fill="${METAL}" stroke="${INK}" stroke-width="2.5"/><rect x="24" y="60" width="52" height="6" fill="${trim}" stroke="${INK}" stroke-width="2"/>`;
    case "round": return `<circle cx="50" cy="48" r="23" fill="${METAL}" stroke="${INK}" stroke-width="2.5"/><path d="M28 54a23 23 0 0 0 44 0" fill="none" stroke="${trim}" stroke-width="4"/>`;
    case "tv": return `<rect x="24" y="30" width="52" height="38" rx="7" fill="${trim}" stroke="${INK}" stroke-width="2.5"/>`;
    case "tall": return `<rect x="30" y="22" width="40" height="46" rx="10" fill="${METAL}" stroke="${INK}" stroke-width="2.5"/><rect x="30" y="30" width="40" height="4" fill="${trim}"/>`;
    default: return `<rect x="25" y="28" width="50" height="40" rx="8" fill="${METAL}" stroke="${INK}" stroke-width="2.5"/><rect x="21" y="42" width="5" height="12" rx="2" fill="${trim}" stroke="${INK}" stroke-width="1.5"/><rect x="74" y="42" width="5" height="12" rx="2" fill="${trim}" stroke="${INK}" stroke-width="1.5"/>`;
  }
}

function robotAntenna(kind, light, head) {
  const top = { dome: 20, round: 25, tv: 30, tall: 22 }[head] ?? 28;
  switch (kind) {
    case "double": return `<path d="M40 ${top}l-4 -10M60 ${top}l4 -10" stroke="${INK}" stroke-width="2.5"/><circle cx="36" cy="${top - 11}" r="3.5" fill="${light}" stroke="${INK}" stroke-width="1.5"/><circle cx="64" cy="${top - 11}" r="3.5" fill="${light}" stroke="${INK}" stroke-width="1.5"/>`;
    case "dish": return `<path d="M50 ${top}v-8" stroke="${INK}" stroke-width="2.5"/><path d="M40 ${top - 14}a10 6 0 0 0 20 0z" fill="${METAL}" stroke="${INK}" stroke-width="2"/><circle cx="50" cy="${top - 16}" r="2.5" fill="${light}"/>`;
    case "spring": return `<path d="M50 ${top}c-4 -2 4 -4 0 -6c-4 -2 4 -4 0 -6" stroke="${INK}" stroke-width="2" fill="none"/><circle cx="50" cy="${top - 15}" r="4" fill="${light}" stroke="${INK}" stroke-width="1.5"/>`;
    case "siren": return `<rect x="43" y="${top - 9}" width="14" height="9" rx="4" fill="${light}" stroke="${INK}" stroke-width="2"/>`;
    case "ears": return `<path d="M44 ${top}l-10 -14M56 ${top}l10 -14" stroke="${INK}" stroke-width="2.5"/><circle cx="34" cy="${top - 15}" r="2.5" fill="${INK}"/><circle cx="66" cy="${top - 15}" r="2.5" fill="${INK}"/>`;
    case "bulb": return `<path d="M50 ${top}v-5" stroke="${INK}" stroke-width="2.5"/><circle cx="50" cy="${top - 10}" r="6" fill="${light}" stroke="${INK}" stroke-width="2"/>`;
    default: return `<path d="M50 ${top}v-10" stroke="${INK}" stroke-width="2.5"/><circle cx="50" cy="${top - 12}" r="3.5" fill="${light}" stroke="${INK}" stroke-width="1.5"/>`;
  }
}

// The robot's face follows the agent's state like the people's do: eyes off on a break, red X's when blocked.
export function robotUri(name, status) {
  const look = ROBOTS[name];
  if (!look) return null;
  const key = `robot:${name}:${status}`;
  if (cache.has(key)) return cache.get(key);
  const mood = status === "paused" || status === "waiting" ? "sleep" : status === "blocked" || status === "error" ? "alarm" : status === "working" ? "happy" : "calm";
  const shirt = `#${LOOKS[name].clothingColor}`;
  const glow = mood === "happy" ? "#7dfcc6" : "#9fe6ff";
  const light = mood === "alarm" ? "#ff5470" : mood === "sleep" ? "#56606e" : mood === "happy" ? "#7dfcc6" : "#ffd166";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">` +
    `<path d="M14 100v-10c0-12 10-20 22-20h28c12 0 22 8 22 20v10z" fill="${shirt}" stroke="${INK}" stroke-width="2.5"/>` +
    `<rect x="40" y="76" width="20" height="12" rx="3" fill="${DARK}"/><circle cx="45" cy="82" r="2" fill="${light}"/><circle cx="55" cy="82" r="2" fill="${glow}"/>` +
    `<rect x="44" y="66" width="12" height="8" fill="${DARK}"/>` +
    robotAntenna(look.antenna, light, look.head) + robotHead(look.head, `#${look.trim}`) + robotEyes(look.eyes, mood, glow) + robotMouth(mood, look.head) +
    `</svg>`;
  const uri = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  cache.set(key, uri);
  return uri;
}

export function portrait(name, status, workspace) {
  return workspace === "slop" ? robotUri(name, status) : avatarUri(name, status);
}

export function creditFor(workspace) {
  return workspace === "slop" ? null : CREDIT;
}
