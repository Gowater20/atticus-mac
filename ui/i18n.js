/**
 * Atticus UI i18n Localization Engine
 * Seamless runtime translation layer for WebKit pages.
 * Supports Italian (it) with zero disruption to upstream HTML markup.
 */

(function () {
  const isItalian = (window.__ATTICUS_LANG__ === 'it') ||
                    (navigator.language && navigator.language.toLowerCase().startsWith('it'));

  if (!isItalian) return;

  const DICT = {
    // Navigation (Settings / Sidebar)
    "Agents": "Agenti",
    "Dictation": "Dettatura",
    "General": "Generale",
    "Intelligence": "Intelligenza",
    "Memory": "Memoria",
    "Meetings": "Riunioni",
    "Usage": "Utilizzo",
    "Account & Access": "Account e Accesso",
    "About & Updates": "Informazioni e Aggiornamenti",
    "Report feedback": "Invia feedback",

    // General Tab
    "Shortcut": "Scorciatoia",
    "Change Shortcut": "Modifica scorciatoia",
    "Use Default": "Ripristina predefinita",
    "Shortcut opens": "La scorciatoia apre",
    "Voice": "Voce",
    "Typing": "Scrittura",
    "Shortcut behavior": "Comportamento scorciatoia",
    "Hold to talk": "Tieni premuto per parlare",
    "Press to toggle": "Premi per attivare/disattivare",
    "Esc cancels.": "Esc per annullare.",
    "Speech model": "Modello vocale",
    "Speech stays on this Mac.": "La voce rimane su questo Mac.",
    "Speech": "Vocale (macOS)",
    "Show answers": "Mostra risposte",
    "As they arrive": "Man mano che arrivano",
    "All at once": "Tutte insieme alla fine",
    "Read answers aloud": "Leggi le risposte a voce",
    "Draw on screen to show you": "Disegna sullo schermo per mostrare",
    "Open at login": "Apri all'avvio del Mac",
    "Pause Atticus": "Metti in pausa Atticus",
    "Show in menu bar": "Mostra nella barra dei menu",
    "Quit Atticus": "Esci da Atticus",
    "Quit": "Esci",
    "Scheduled routines": "Routine programmate",

    // Dictation Tab
    "Dictate anywhere": "Dettatura ovunque",
    "Dictation shortcut": "Scorciatoia dettatura",
    "Dictated text": "Testo dettato",
    "Verbatim": "Testuale",
    "Clean up": "Migliorato",
    "Dictionary": "Dizionario personalizzato",
    "Add Word": "Aggiungi parola",
    "History": "Cronologia",
    "Clear All…": "Cancella tutto…",
    "Save dictation history": "Salva cronologia dettature",
    "Only on this Mac.": "Solo su questo Mac.",

    // Intelligence Tab
    "Model": "Modello AI",
    "AI client": "Client AI",
    "Claude": "Claude",
    "Gemini": "Google Gemini",
    "Devin": "Devin",
    "Pi": "Pi",
    "Cheapest": "Più economico",
    "Balanced": "Bilanciato",
    "Most capable": "Massima potenza",

    // HUD / Popup / UI Overlays
    "Full access": "Accesso completo",
    "Safe mode is off. Click to turn it on.": "Modalità sicura disattivata. Clicca per attivarla.",
    "Safe mode is on. Click to turn it off.": "Modalità sicura attiva. Clicca per disattivarla.",
    "Point at your screen": "Indica sullo schermo",
    "Marked": "Contrassegnato",
    "Got it": "Ho capito",
    "Talk instead": "Parla a voce",
    "Open ↗": "Apri ↗",
    "Atticus is paused": "Atticus è in pausa",
    "Resume": "Riprendi",
    "Atticus’s helper couldn’t start": "Impossibile avviare il servizio di Atticus",
    "Open Setup": "Apri configurazione",
    "Retry": "Riprova",
    "Not now": "Non ora",
    "Not Now": "Non ora",
    "Allow": "Consenti",
    "Don’t Allow": "Non consentire",
    "Help make Atticus better?": "Aiuta a migliorare Atticus?",
    "Help Improve": "Contribuisci",
    "None of these": "Nessuno di questi",
    "All choices": "Tutte le scelte",
    "Use this": "Usa questo",
    "Settings ›": "Impostazioni ›",
    "Review your feedback before opening GitHub.": "Controlla il tuo feedback prima di aprire GitHub.",

    // Onboarding
    "Welcome to Atticus": "Benvenuto in Atticus",
    "Choose your AI": "Scegli la tua Intelligenza Artificiale",
    "Sign in": "Accedi",
    "Microphone": "Microfono",
    "Accessibility": "Accessibilità",
    "Screen Recording": "Registrazione schermo",
    "Get Started": "Inizia subito",
    "Continue": "Continua",
    "Back": "Indietro",
    "Finish": "Fine",
    "Done": "Fatto"
  };

  const PLACEHOLDERS = {
    "Add a word or phrase": "Aggiungi una parola o frase",
    "Something else…": "Altro…",
    "Ask anything…": "Chiedi qualsiasi cosa…",
    "Type a message…": "Scrivi un messaggio…",
    "Search": "Cerca"
  };

  function translateNode(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const val = node.nodeValue.trim();
      if (val && DICT[val]) {
        node.nodeValue = node.nodeValue.replace(val, DICT[val]);
      }
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      // Attribute translations
      const ph = node.getAttribute('placeholder');
      if (ph && PLACEHOLDERS[ph]) {
        node.setAttribute('placeholder', PLACEHOLDERS[ph]);
      }
      const title = node.getAttribute('title');
      if (title && DICT[title]) {
        node.setAttribute('title', DICT[title]);
      }
      const aria = node.getAttribute('aria-label');
      if (aria && DICT[aria]) {
        node.setAttribute('aria-label', DICT[aria]);
      }

      // Check button / label direct text
      for (const child of node.childNodes) {
        translateNode(child);
      }
    }
  }

  function runTranslation() {
    if (document.body) {
      translateNode(document.body);
    }
  }

  // Run on load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', runTranslation);
  } else {
    runTranslation();
  }

  // Observer for dynamic content insertions (e.g. tabs switching, dialogs)
  let scheduled = false;
  const observer = new MutationObserver((mutations) => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(() => {
        runTranslation();
        scheduled = false;
      });
    }
  });

  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener('DOMContentLoaded', () => {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  }
})();

