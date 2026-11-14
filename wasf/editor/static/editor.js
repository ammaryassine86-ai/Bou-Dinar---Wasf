"use strict";

const STATUS_LABELS = { brouillon: "Texte IA", modifie: "Modifié", valide: "Validé", ignore: "Ignoré" };
const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
const state = { data: null, filter: "tous" };

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function words(text) {
  const trimmed = (text || "").trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

const seconds = (value) => Number(value || 0).toFixed(1).replace(".", ",");
const normalized = (text) => (text || "").split(/\s+/).filter(Boolean).join(" ");

// What the last export measured for this passage, while the text is still the one it measured.
function voiceStatus(seg, text) {
  const m = seg.voix_mesuree || {};
  if (!m.moteur) return null;
  if (normalized(text) !== normalized(m.texte)) {
    return { cls: "stale", text: `Texte modifié depuis la dernière mesure (${m.moteur}) : la voix sera mesurée au prochain export.` };
  }
  const speed = m.acceleration > 1 ? `, accélérée ×${String(m.acceleration).replace(".", ",")}` : "";
  const measured = `Voix mesurée à l'export (${m.moteur}) : ${seconds(m.duree_voix_s)} s${speed} pour ${seconds(m.duree_disponible_s)} s disponibles`;
  if (m.deborde || m.chevauche) {
    const why = [m.deborde ? `déborde de ${seconds(m.depassement_s)} s` : "", m.chevauche ? `chevauche la voix de ${m.chevauche}` : ""].filter(Boolean).join(" et ");
    return { cls: "over", text: `${measured} : elle ${why}. Raccourcissez le texte ; l'export final est refusé tant qu'elle déborde.` };
  }
  return { cls: "fits", text: `${measured} : elle tient dans la pause.` };
}

let toastTimer;
function toast(message, isError = false) {
  const box = document.getElementById("toast");
  box.textContent = message;
  box.className = "show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.className = ""), isError ? 6000 : 2500);
}

// The session token the server wrote into this page: every API call sends it back, so that
// no other web page open in the browser can read or change the project.
const TOKEN = (document.querySelector('meta[name="wasf-jeton"]') || {}).content || "";

async function api(path, body) {
  const options = body === undefined ? { headers: { "X-Wasf-Jeton": TOKEN } } : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Wasf-Jeton": TOKEN },
    body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const json = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(json.erreur || `Erreur ${response.status}`);
    error.payload = json;
    throw error;
  }
  return json;
}

function applySummary(summary) {
  Object.assign(state.data, {
    projet: summary.projet, compteurs: summary.compteurs, signataire: summary.signataire,
    sans_alerte: summary.sans_alerte, a_verifier: summary.a_verifier,
    langue_nom: summary.langue_nom, rtl: summary.rtl, fichier: summary.fichier,
    simulation: summary.simulation, echantillon: summary.echantillon,
    mots_par_seconde: summary.mots_par_seconde, preparation_en_cours: summary.preparation_en_cours,
  });
  renderHeader();
}

function pending(seg) {
  return seg.statut !== "valide" && seg.statut !== "ignore";
}

function flagged(seg) {
  return pending(seg) && (seg.signalements || []).length > 0;
}

function renderHeader() {
  const { projet, compteurs, langue_nom, fichier } = state.data;
  document.getElementById("film").textContent = projet.film;
  document.getElementById("simulation").hidden = !state.data.simulation;
  document.getElementById("preparation").hidden = !state.data.preparation_en_cours;
  document.getElementById("meta").textContent =
    `${langue_nom} · ${state.data.segments.length} passages · IA : ${projet.fournisseur} (${projet.modele})`;
  const done = compteurs.valide + compteurs.ignore;
  const total = state.data.segments.length || 1;
  const bar = document.getElementById("progress");
  bar.setAttribute("aria-valuemax", total);
  bar.setAttribute("aria-valuenow", done);
  document.getElementById("progress-fill").style.width = `${(100 * done) / total}%`;
  document.getElementById("progress-label").textContent =
    `${compteurs.valide} validé(s) · ${compteurs.ignore} ignoré(s) · ${total - done} à relire`;
  const descr = document.getElementById("descripteur");
  if (document.activeElement !== descr) descr.value = projet.descripteur || "";
  const real = document.getElementById("realisateur");
  if (document.activeElement !== real) real.value = projet.realisateur || "";
  document.getElementById("validation_realisateur").checked = !!projet.validation_realisateur;
  document.getElementById("export-cmd").textContent = `wasf exporter "${fichier}"`;

  const clean = state.data.sans_alerte || 0;
  const sample = state.data.echantillon || [];
  const bulk = document.getElementById("valider-lot");
  if (sample.length) {
    // One click is never blind: a random sample is validated one by one first.
    bulk.disabled = true;
    bulk.textContent = `D'abord, relisez ${plural(sample.length, "passage tiré au hasard", "passages tirés au hasard")}`;
  } else {
    bulk.disabled = clean === 0;
    bulk.textContent = clean
      ? (clean > 1 ? `Valider les ${clean} passages sans alerte` : "Valider le passage sans alerte")
      : "Aucun passage sans alerte à valider";
  }
  const signer = state.data.signataire;
  const toCheck = state.data.a_verifier || 0;
  document.getElementById("lot-info").textContent =
    (sample.length ? `Échantillon à valider un par un : ${sample.join(", ")} (filtre « Échantillon »), puis ${plural(clean, "passage", "passages")} en un clic · ` : "") +
    `${plural(toCheck, "passage signalé", "passages signalés")} à vérifier un par un · ` +
    (signer ? `signature : ${signer}` : "indiquez qui signe");
}

function inSample(seg) {
  return (state.data.echantillon || []).includes(seg.id);
}

function showFilter(name) {
  state.filter = name;
  for (const b of document.querySelectorAll(".filters button")) b.setAttribute("aria-pressed", String(b.dataset.filtre === name));
  renderList();
}

function visible(seg) {
  if (state.filter === "echantillon") return inSample(seg);
  if (state.filter === "signales") return flagged(seg);
  if (state.filter === "a_faire") return pending(seg);
  if (state.filter === "valide") return seg.statut === "valide";
  return true;
}

function renderList() {
  const list = document.getElementById("passages");
  list.replaceChildren(...state.data.segments.filter(visible).map(card));
  if (!list.children.length) list.append(el("p", { class: "hint" }, "Aucun passage dans ce filtre."));
}

function checksList(checks) {
  // The voice-length warning is already shown, in full, right under the text (voiceStatus).
  const shown = (checks || []).filter((c) => c.code !== "voix_trop_longue");
  return el("ul", { class: "checks" }, shown.map((c) => el("li", { class: c.niveau }, c.message)));
}

function card(seg) {
  const lang = state.data.projet.langue;
  const dir = state.data.rtl ? "rtl" : "ltr";
  const textarea = el("textarea", { id: `txt-${seg.id}`, rows: 3, dir, lang: lang === "aeb" ? "aeb" : lang });
  textarea.value = seg.texte || "";

  const count = el("span", {}, "");
  const fill = el("i");
  const meter = el("div", { class: "meter", "aria-live": "polite" }, count, el("div", { class: "bar" }, fill));
  const rate = state.data.mots_par_seconde || 2.5;
  const voice = el("p", { class: "voice", "aria-live": "polite" });
  const updateMeter = () => {
    const n = words(textarea.value);
    // Estimated from the words at the track's speaking rate; each export times the real voice.
    count.textContent = `${n} / ${seg.budget_mots} mots · environ ${seconds(n / rate)} s à dire pour ${seconds(seg.duree_parole)} s de pause`;
    fill.style.width = `${Math.min(100, (100 * n) / seg.budget_mots)}%`;
    meter.classList.toggle("over", n > seg.budget_mots || n / rate > seg.duree_parole);
    const status = voiceStatus(seg, textarea.value);
    voice.hidden = !status;
    if (status) {
      voice.className = `voice ${status.cls}`;
      voice.textContent = status.text;
    }
  };
  updateMeter();
  textarea.addEventListener("input", updateMeter);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      send(seg.id, "valider");
    }
  });

  const note = el("input", { type: "text", id: `note-${seg.id}`, placeholder: "Question, doute, idée…" });
  note.value = seg.note || "";

  const context = el("dl", { class: "context" },
    seg.dialogue_avant ? [el("dt", {}, "Dialogue avant"), el("dd", { dir: "auto" }, `« ${seg.dialogue_avant} »`)] : null,
    seg.dialogue_apres ? [el("dt", {}, "Dialogue après"), el("dd", { dir: "auto" }, `« ${seg.dialogue_apres} »`)] : null,
    seg.a_remarquer ? [el("dt", {}, "À faire remarquer"), el("dd", { dir: "auto" }, seg.a_remarquer)] : null,
    seg.a_eviter && seg.a_eviter.length
      ? [el("dt", {}, "À ne jamais dire"), el("dd", { class: "avoid", dir: "auto" }, seg.a_eviter.join(", "))] : null,
  );

  const confidence = seg.confiance_ia == null ? "" : ` · confiance ${Math.round(seg.confiance_ia * 100)} %`;
  const draft = el("div", { class: "draft" },
    el("h4", {}, `Texte écrit par l'IA${confidence}`),
    el("p", { dir }, seg.brouillon_ia || "(aucun texte)"));

  // What the model says it saw, apart from what it supposes: the director checks one against the other.
  const observations = seg.observations_ia || [];
  const supposed = (seg.emotions_ia || []).map((e) => `${e.emotion}${e.qui ? ` (${e.qui})` : ""}` +
    (e.indices && e.indices.length ? ` : ${e.indices.join(", ")}` : " : aucun signe donné") +
    (e.certitude == null ? "" : ` · certitude ${Math.round(e.certitude * 100)} %`));
  const changes = (seg.changements_ia || []).map((c) => `${c.qui ? `${c.qui} : ` : ""}${c.avant} → ${c.apres}` +
    (c.images && c.images.length ? ` (images ${c.images.join(", ")})` : ""));
  const between = (seg.interactions_ia || []).map((x) => `${x.qui || "?"} → ${x.envers || "?"} : ${x.geste}`);
  const looked = seg.seconde_lecture || [];
  const rejected = looked.filter((r) => r.visible === "non");
  const recheck = looked.length
    ? `Seconde lecture : ${looked.filter((r) => r.visible === "oui").length} confirmé(s), ` +
      `${rejected.length} non vu(s), ${looked.filter((r) => r.visible === "incertain").length} incertain(s)` +
      (rejected.length ? ` (« ${rejected.map((r) => r.affirmation).join(" », « ")} »)` : "")
    : "";
  const seen = observations.length || supposed.length || changes.length || between.length || recheck
    ? el("div", { class: "seen" },
        el("h4", {}, "Ce que l'IA a vu"),
        observations.length ? el("ul", { dir }, observations.map((o) => el("li", {}, o))) : null,
        changes.length ? el("p", { class: "supposed", dir }, `Changements : ${changes.join(" ; ")}`) : null,
        between.length ? el("p", { class: "supposed", dir }, `Entre personnages : ${between.join(" ; ")}`) : null,
        recheck ? el("p", { class: "supposed", dir }, recheck) : null,
        supposed.length ? el("p", { class: "supposed", dir }, `Émotions supposées : ${supposed.join(" ; ")}`) : null)
    : null;

  const journal = (seg.journal_agent || []).map((step) => {
    if (step.resultats) return el("li", {}, `${step.etape} : ${step.resultats.map((r) => r.message).join(" ")}`);
    if (step.texte !== undefined) return el("li", {}, `${step.etape} : « ${step.texte} »`);
    return el("li", {}, `${step.etape} : ${step.message || ""}`);
  });

  const info = seg.images_info || seg.images.map((src) => ({ src, quand: "", avant: false }));
  const frames = el("div", { class: "frames" }, info.map((image, i) => {
    const when = image.quand ? `${image.avant ? "Avant la pause" : "Pendant la pause"} · ${image.quand}` : "";
    return el("figure", {},
      el("img", { src: `/${image.src}`, loading: "lazy",
                  alt: `Image ${i + 1} du passage ${seg.id}, extraite du film${when ? ` (${when.toLowerCase()})` : ""}` }),
      when ? el("figcaption", { class: image.avant ? "before" : null }, when) : null);
  }));

  const signed = seg.statut === "valide" || seg.statut === "ignore"
    ? el("p", { class: "signed" }, `${STATUS_LABELS[seg.statut]} par ${seg.valide_par || "?"} le ${(seg.valide_le || "").replace("T", " à ").slice(0, 21)}` +
        (seg.valide_en_lot ? " · en un clic, sans alerte" : ""))
    : null;

  const actions = el("div", { class: "actions" },
    seg.statut === "valide" || seg.statut === "ignore"
      ? el("button", { type: "button", onclick: () => send(seg.id, "rouvrir") }, "Rouvrir")
      : [
          el("button", { type: "button", class: "primary", onclick: () => send(seg.id, "valider") }, "Valider et signer"),
          el("button", { type: "button", onclick: () => send(seg.id, "enregistrer") }, "Enregistrer"),
          el("button", { type: "button", onclick: () => { textarea.value = seg.brouillon_ia; updateMeter(); } }, "Reprendre le texte de l'IA"),
          el("button", { type: "button", class: "ghost", onclick: () => send(seg.id, "ignorer") }, "Rien à décrire ici"),
        ]);

  const alert = flagged(seg);
  return el("article", { class: `passage ${seg.statut}${alert ? " flagged" : ""}`, id: `card-${seg.id}`, "aria-labelledby": `h-${seg.id}` },
    el("header", {},
      el("h3", { id: `h-${seg.id}` }, `Passage ${seg.id} · ${seg.debut_txt} → ${seg.fin_txt}`),
      el("div", { class: "tags" },
        inSample(seg) ? el("span", { class: "sample" }, "Échantillon : à relire un par un") : null,
        alert ? el("span", { class: "flag" }, `À vérifier : ${seg.signalements.join(", ")}`) : null,
        el("span", { class: "badge" }, STATUS_LABELS[seg.statut] || seg.statut))),
    el("p", { class: "facts" }, `Pause de ${seg.duree_parole.toString().replace(".", ",")} s · ${seg.budget_mots} mots au maximum · source : ${seg.source}`),
    el("div", { class: "body" },
      frames,
      el("div", { class: "content" },
        context,
        draft,
        seen,
        el("label", { for: `txt-${seg.id}` }, "Texte final, lu aux spectateurs"),
        textarea,
        meter,
        voice,
        checksList(seg.verifications),
        el("label", { class: "note", for: `note-${seg.id}` }, "Note pour l'équipe"),
        note,
        actions,
        signed,
        journal.length ? el("details", { class: "journal" },
          el("summary", {}, `Journal de l'agent (${journal.length} étapes)`), el("ol", {}, journal)) : null)));
}

async function send(segId, action) {
  const textarea = document.getElementById(`txt-${segId}`);
  const note = document.getElementById(`note-${segId}`);
  try {
    const result = await api(`/api/passage/${segId}`, {
      action, texte: textarea ? textarea.value : undefined, note: note ? note.value : undefined,
    });
    replaceSegment(result.passage);
    applySummary(result);
    const messages = { valider: "Passage validé et signé.", ignorer: "Passage ignoré.", rouvrir: "Passage rouvert.", enregistrer: "Enregistré." };
    toast(messages[action]);
    if (action === "valider") focusNext(segId);
  } catch (error) {
    if (error.payload && error.payload.passage) replaceSegment(error.payload.passage);
    toast(error.message, true);
  }
}

function replaceSegment(seg) {
  const index = state.data.segments.findIndex((s) => s.id === seg.id);
  if (index >= 0) state.data.segments[index] = seg;
  const old = document.getElementById(`card-${seg.id}`);
  if (old) old.replaceWith(card(seg));
}

function focusNext(segId) {
  const index = state.data.segments.findIndex((s) => s.id === segId);
  const next = state.data.segments.slice(index + 1).find((s) => s.statut !== "valide" && s.statut !== "ignore");
  if (next) {
    const box = document.getElementById(`txt-${next.id}`);
    if (box) { box.focus(); box.scrollIntoView({ behavior: "smooth", block: "center" }); }
  }
}

async function validateClean() {
  const clean = state.data.sans_alerte || 0;
  if (!clean) return;
  const signer = state.data.signataire || "?";
  if (!window.confirm(`Valider ${plural(clean, "passage", "passages")} sans alerte, signature « ${signer} » ? Les passages signalés restent à vérifier un par un.`)) return;
  try {
    const result = await api("/api/valider-sans-alerte", {});
    state.data.segments = result.segments;
    applySummary(result);
    renderList();
    toast(`${plural(result.valides.length, "passage validé", "passages validés")} en un clic.`);
  } catch (error) {
    if (error.payload && error.payload.echantillon) {
      state.data.echantillon = error.payload.echantillon;
      renderHeader();
      showFilter("echantillon");
    }
    toast(error.message, true);
  }
}

async function saveTeam(field, value) {
  try {
    const result = await api("/api/projet", { [field]: value });
    applySummary(result);
    if (result.avis) toast(result.avis, true);
    else toast(field === "validation_realisateur" ? (value ? "Piste approuvée par la réalisation." : "Approbation retirée.") : "Enregistré.");
  } catch (error) {
    toast(error.message, true);
    renderHeader();
  }
}

async function init() {
  state.data = await api("/api/projet");
  if (state.data.rtl) document.body.classList.add("rtl");
  renderHeader();
  renderList();
  document.getElementById("descripteur").addEventListener("change", (e) => saveTeam("descripteur", e.target.value));
  document.getElementById("realisateur").addEventListener("change", (e) => saveTeam("realisateur", e.target.value));
  document.getElementById("validation_realisateur").addEventListener("change", (e) => saveTeam("validation_realisateur", e.target.checked));
  document.getElementById("valider-lot").addEventListener("click", validateClean);
  for (const button of document.querySelectorAll(".filters button")) {
    button.addEventListener("click", () => showFilter(button.dataset.filtre));
  }
}

init().catch((error) => toast(`Impossible de charger le projet : ${error.message}`, true));
