// Painel do night-shift: avisos (toasts) e atalhos de teclado. Sem dependências além do htmx.

// ------------------------------------------------------------------ avisos

const TOAST_MS = 6000;

function showToast({ message, undo, card: cardSel }) {
  const box = document.getElementById("toasts");
  if (!box) return;
  const el = document.createElement("div");
  el.className = "toast";
  el.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = message;
  el.append(text);
  if (undo) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn small";
    btn.textContent = "Desfazer";
    btn.title = "Desfazer (z)";
    btn.onclick = () => {
      // Clica no botão de desfazer do próprio cartão: é o mesmo caminho de um clique normal
      // (htmx.ajax chamado por fora quebra ao tratar a resposta e não troca o cartão).
      const card = cardSel && document.querySelector(cardSel);
      const inCard = card && card.querySelector(`[hx-post="${undo}"]`);
      if (inCard) inCard.click();
      else
        fetch(undo, { method: "POST", headers: { "HX-Request": "true" } }).then(() =>
          location.reload()
        );
      close();
    };
    el.append(btn);
    lastUndo = btn;
  }
  box.append(el);
  const timer = setTimeout(close, TOAST_MS);
  function close() {
    clearTimeout(timer);
    if (lastUndo && el.contains(lastUndo)) lastUndo = null;
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 200);
  }
}

let lastUndo = null;
document.body.addEventListener("toast", (e) => showToast(e.detail));

// ------------------------------------------------------------------ atalhos

// Cartões navegáveis (Fila e Outreach); os já decididos ficam de fora.
const CARDS = ".card:not(.decided)";
let selected = -1;

function cards() {
  return [...document.querySelectorAll(CARDS)];
}

function select(index) {
  const list = cards();
  if (!list.length) return;
  selected = Math.max(0, Math.min(index, list.length - 1));
  list.forEach((c, i) => c.classList.toggle("selected", i === selected));
  list[selected].scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function current() {
  return cards()[selected] || null;
}

function press(key) {
  const card = current();
  const btn = card && card.querySelector(`[data-key="${key}"]`);
  if (btn) btn.click();
}

// Depois de Done/Descartar o cartão vira "decidido": a seleção fica no mesmo lugar, que
// agora é a próxima vaga.
document.body.addEventListener("htmx:afterSettle", () => {
  if (selected >= 0) select(selected);
});

let pendingG = false;
const GO = { h: "/", v: "/ao-vivo", f: "/fila", u: "/funil", o: "/outreach", m: "/mercado" };

document.addEventListener("keydown", (e) => {
  const tag = (e.target.tagName || "").toLowerCase();
  if (e.key === "Escape") {
    const help = document.getElementById("shortcuts");
    if (help && help.open) help.close();
    if (["input", "textarea", "select"].includes(tag)) e.target.blur();
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (["input", "textarea", "select"].includes(tag) || e.target.isContentEditable) return;

  if (pendingG) {
    pendingG = false;
    if (GO[e.key]) location.href = GO[e.key];
    return;
  }
  // "?" chega como "/" com Shift em alguns teclados (e na automação de teste).
  const key = e.key === "/" && e.shiftKey ? "?" : e.key;
  // Enter num link ou botão focado continua sendo o clique normal.
  if (key === "Enter" && ["a", "button", "summary"].includes(tag)) return;
  switch (key) {
    case "j": select(selected + 1); break;
    case "k": select(selected < 0 ? 0 : selected - 1); break;
    case "o":
    case "Enter": {
      const more = current() && current().querySelector("details.more");
      if (more) more.open = !more.open;
      else return;
      break;
    }
    case "a": press("a"); break;
    case "d": press("d"); break;
    case "x": press("x"); break;
    case "c": press("c"); break;
    case "z": if (lastUndo) lastUndo.click(); break;
    case "/": {
      const search = document.querySelector("input[type=search]");
      if (!search) return;
      search.focus();
      search.select();
      break;
    }
    case "b": document.querySelector("[data-key=b]")?.click(); break;
    case "g": pendingG = true; setTimeout(() => (pendingG = false), 1200); break;
    case "?": document.getElementById("shortcuts")?.showModal(); break;
    default: return;
  }
  e.preventDefault();
});
