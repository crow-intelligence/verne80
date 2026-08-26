/* Every user-facing string comes from data/strings.json, never from the markup.
 *
 * The catalogue is built in Python (src/verne80/strings.py) so that key parity and
 * placeholder parity are asserted by a test — those two are the only things that actually
 * break a translated page. A translator who drops {n} from a day count ships "day of",
 * and nothing else would notice.
 *
 * Untranslated keys fall back to English one at a time, with one warning each. A blank is
 * never rendered: a missing translation should look like English, not like a bug.
 */

const FALLBACK = "en";

let catalogue = { default: FALLBACK, languages: [] };
let language = FALLBACK;
const warned = new Set();

/** Pick the language: an explicit ?lang= beats a remembered choice beats the browser. */
export function chooseLanguage(strings) {
  catalogue = strings;
  const offered = new Set((strings.languages || []).map((entry) => entry.code));
  const asked = new URLSearchParams(location.search).get("lang");
  let remembered = null;
  try {
    remembered = localStorage.getItem("lang");
  } catch {
    // A browser refusing storage is not a reason to fail to render a page.
  }
  const browser = (navigator.language || "").slice(0, 2);
  for (const candidate of [asked, remembered, browser, strings.default, FALLBACK]) {
    if (candidate && offered.has(candidate)) {
      language = candidate;
      break;
    }
  }
  document.documentElement.lang = language;
  return language;
}

/**
 * One string, with its {placeholders} filled.
 *
 * Placeholders are named rather than positional so a translator can reorder them, which is
 * most of what translating a sentence is.
 */
export function t(key, values = {}) {
  const entries = catalogue[language] || {};
  let text = entries[key];
  if (text === undefined) {
    text = (catalogue[FALLBACK] || {})[key];
    if (text !== undefined && language !== FALLBACK && !warned.has(key)) {
      warned.add(key);
      console.warn(`i18n: ${language} has no ${key}; showing the ${FALLBACK} text`);
    }
  }
  if (text === undefined) {
    console.warn(`i18n: no string for ${key} in any language`);
    return key;
  }
  return text.replace(/\{(\w+)\}/g, (whole, name) =>
    name in values ? String(values[name]) : whole,
  );
}

/**
 * Fill every [data-i18n] node in the document.
 *
 * Strings carry no markup — a tag inside a catalogue entry is an injection hole and an
 * untranslatable blob at once — so this sets textContent and never innerHTML. A sentence
 * that needs a link is split into .before and .after keys with the anchor built between.
 */
export function localise(root = document) {
  for (const node of root.querySelectorAll("[data-i18n]")) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const node of root.querySelectorAll("[data-i18n-label]")) {
    node.setAttribute("aria-label", t(node.dataset.i18nLabel));
  }
}
