/**
 * FareWise — Background Service Worker (Manifest V3)
 *
 * Responsibilities:
 *  1. On install  → configure side-panel behaviour & open welcome tab
 *  2. Keyboard shortcuts → open/toggle the side panel with the right mode
 *  3. Action-button click → open side panel (MV3 requires explicit call)
 *
 * NOT responsible for:
 *  - WebSocket connections (those live in sidepanel.js — SW is ephemeral)
 *  - Nova API calls (all in FastAPI backend)
 */

// ── 1. INSTALL ───────────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason === chrome.runtime.OnInstalledReason.INSTALL) {
    // Make clicking the action icon open the side panel directly
    // (users can still open the popup by right-clicking the icon)
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

    // Open welcome / onboarding page on first install
    chrome.tabs.create({
      url: chrome.runtime.getURL('onboarding/onboarding.html'),
      active: true,
    });

    // Seed default settings
    await chrome.storage.local.set({
      selectedCards: ['hdfc-regalia', 'sbi-simplyclick', 'axis-flipkart'],
      defaultMode:   'products',
      apiUrl:        'http://localhost:8000',
    });

    console.log('[FareWise] Installed — defaults seeded.');
  }

  if (reason === chrome.runtime.OnInstalledReason.UPDATE) {
    console.log('[FareWise] Updated to', chrome.runtime.getManifest().version);
  }
});

// ── 2. ACTION BUTTON CLICK ───────────────────────────────────────────────────
// When openPanelOnActionClick = true Chrome handles this automatically,
// but we also need to handle it explicitly for tabs where the side panel
// was previously closed.
chrome.action.onClicked.addListener(async (tab) => {
  try {
    await chrome.sidePanel.open({ tabId: tab.id });
  } catch (err) {
    // Tab may not support side panels (e.g. chrome:// pages) — silently ignore
    console.warn('[FareWise] Could not open side panel:', err.message);
  }
});

// ── 3. KEYBOARD SHORTCUTS ────────────────────────────────────────────────────
chrome.commands.onCommand.addListener(async (command, tab) => {
  const actions = {
    'toggle-side-panel':    { pendingMode: null,       pendingAction: 'toggle' },
    'quick-product-search': { pendingMode: 'products', pendingAction: null },
    'quick-travel-search':  { pendingMode: 'travel',   pendingAction: null },
  };

  const payload = actions[command];
  if (!payload) return;

  // Store the mode/action intent before opening — sidepanel reads this on load
  const update = {};
  if (payload.pendingMode)   update.pendingMode   = payload.pendingMode;
  if (payload.pendingAction) update.pendingAction = payload.pendingAction;
  if (Object.keys(update).length) await chrome.storage.local.set(update);

  try {
    await chrome.sidePanel.open({ tabId: tab.id });
  } catch (err) {
    console.warn('[FareWise] Shortcut panel open failed:', err.message);
  }
});

// ── 4. CONTEXT MENU (right-click on page image) ──────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id:       'farewise-compare-image',
    title:    '🎯 Compare price with FareWise',
    contexts: ['image'],
  });

  chrome.contextMenus.create({
    id:       'farewise-compare-selection',
    title:    '🎯 Search FareWise for "%s"',
    contexts: ['selection'],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === 'farewise-compare-image') {
    await chrome.storage.local.set({
      pendingMode:   'products',
      pendingImageUrl: info.srcUrl,
    });
    await chrome.sidePanel.open({ tabId: tab.id });
  }

  if (info.menuItemId === 'farewise-compare-selection') {
    await chrome.storage.local.set({
      pendingMode:  'products',
      pendingQuery: info.selectionText,
    });
    await chrome.sidePanel.open({ tabId: tab.id });
  }
});

// ── 5. MESSAGE RELAY ─────────────────────────────────────────────────────────
// Sidepanel can't use chrome.tabs directly in some contexts — relay through SW
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'OPEN_URL') {
    chrome.tabs.create({ url: message.url, active: true });
    sendResponse({ ok: true });
  }

  if (message.type === 'GET_ACTIVE_TAB_URL') {
    chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
      sendResponse({ url: tab?.url ?? null });
    });
    return true; // keep channel open for async response
  }

  if (message.type === 'COPY_TO_CLIPBOARD') {
    // Workaround: SW can't access clipboard — write via offscreen document
    // For now just acknowledge; sidepanel handles clipboard natively
    sendResponse({ ok: false, reason: 'use sidepanel clipboard API' });
  }
});

// ── 6. KEEP-ALIVE PING (workaround for MV3 SW termination) ──────────────────
// Chrome may terminate idle SWs before onCommand fires.
// The sidepanel pings every 20s to keep it alive while the panel is open.
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'KEEPALIVE_PING') {
    // Receiving the message is enough to reset the idle timer — no-op body needed
  }
});

console.log('[FareWise] Service worker registered.');
