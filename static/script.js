const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const messagesEl = document.getElementById("messages");
const newChatBtn = document.getElementById("new-chat-btn");
const conversationListEl = document.getElementById("conversation-list");
const chatTitleEl = document.getElementById("chat-title");

let currentConversationId = null;

function addMessage(text, type) {
  const el = document.createElement("div");
  el.className = `message ${type}`;
  el.textContent = text;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return el;
}

function clearMessages() {
  messagesEl.innerHTML = "";
}

function showEmptyState() {
  clearMessages();
  const el = document.createElement("div");
  el.className = "empty-state";
  el.textContent = "Start a new conversation below.";
  messagesEl.appendChild(el);
}

async function fetchConversations() {
  const res = await fetch("/api/conversations");
  return res.json();
}

async function fetchMessages(conversationId) {
  const res = await fetch(`/api/conversations/${conversationId}/messages`);
  return res.json();
}

async function renderConversationList() {
  const conversations = await fetchConversations();
  conversationListEl.innerHTML = "";

  conversations.forEach((conv) => {
    const item = document.createElement("div");
    item.className = "conversation-item" + (conv.id === currentConversationId ? " active" : "");

    const titleSpan = document.createElement("span");
    titleSpan.className = "title";
    titleSpan.textContent = conv.title;
    item.appendChild(titleSpan);

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "delete-btn";
    deleteBtn.textContent = "✕";
    deleteBtn.title = "Delete conversation";
    deleteBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await fetch(`/api/conversations/${conv.id}`, { method: "DELETE" });
      if (conv.id === currentConversationId) {
        currentConversationId = null;
        showEmptyState();
        chatTitleEl.textContent = "Gemini Chatbot";
      }
      renderConversationList();
    });
    item.appendChild(deleteBtn);

    item.addEventListener("click", () => openConversation(conv.id, conv.title));
    conversationListEl.appendChild(item);
  });

  return conversations;
}

async function openConversation(conversationId, title) {
  currentConversationId = conversationId;
  chatTitleEl.textContent = title || "Gemini Chatbot";
  clearMessages();

  const messages = await fetchMessages(conversationId);
  if (messages.length === 0) {
    showEmptyState();
  } else {
    messages.forEach((m) => addMessage(m.content, m.role));
  }

  renderConversationList(); // refresh active highlight
}

async function createNewConversation() {
  const res = await fetch("/api/conversations", { method: "POST" });
  const conv = await res.json();
  await renderConversationList();
  await openConversation(conv.id, conv.title);
}

newChatBtn.addEventListener("click", createNewConversation);

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  // Auto-create a conversation if none is selected yet.
  if (currentConversationId === null) {
    const res = await fetch("/api/conversations", { method: "POST" });
    const conv = await res.json();
    currentConversationId = conv.id;
    clearMessages();
  }

  addMessage(message, "user");
  input.value = "";
  input.disabled = true;
  form.querySelector("button").disabled = true;

  const thinkingEl = addMessage("...", "model");

  try {
    const res = await fetch(`/api/conversations/${currentConversationId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Something went wrong");
    thinkingEl.textContent = data.reply;
    await renderConversationList(); // title may have auto-updated
  } catch (err) {
    thinkingEl.remove();
    addMessage(err.message, "error");
  } finally {
    input.disabled = false;
    form.querySelector("button").disabled = false;
    input.focus();
  }
});

// Initial load
(async function init() {
  const conversations = await renderConversationList();
  if (conversations.length > 0) {
    await openConversation(conversations[0].id, conversations[0].title);
  } else {
    showEmptyState();
  }
})();
