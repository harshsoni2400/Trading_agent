"use client";

import { useState, useRef, useEffect } from "react";
import Nav from "@/components/Nav";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage: Message = { role: "user", content: input };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: newMessages }),
      });
      const data = await res.json();
      setMessages([...newMessages, { role: "assistant", content: data.reply || data.error }]);
    } catch {
      setMessages([...newMessages, { role: "assistant", content: "Error connecting to Claude." }]);
    }
    setLoading(false);
  }

  return (
    <>
      <Nav />
      <main className="flex-1 flex flex-col max-h-[calc(100vh-60px)]">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-gray-500 mt-20">
              <p className="text-lg mb-2">Trading Assistant</p>
              <p className="text-sm">Ask about your trades, P&L, signals, or give orders.</p>
              <div className="mt-6 grid grid-cols-2 gap-2 max-w-md mx-auto">
                {["What are my open positions?", "Analyze RELIANCE for intraday",
                  "What is my P&L today?", "Buy 10 TCS at market"].map((q) => (
                  <button key={q} onClick={() => { setInput(q); }}
                    className="text-left text-xs bg-gray-900 border border-gray-800 rounded-lg p-3 hover:border-gray-600 text-gray-300">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[70%] rounded-xl px-4 py-3 text-sm whitespace-pre-wrap ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-900 border border-gray-800 text-gray-200"
              }`}>
                {msg.content}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 text-sm text-gray-400">
                Thinking...
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <form onSubmit={sendMessage} className="p-4 border-t border-gray-800 bg-gray-950">
          <div className="flex gap-3 max-w-3xl mx-auto">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about trades, signals, or give orders..."
              className="flex-1 p-3 bg-gray-900 border border-gray-700 rounded-xl text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
              disabled={loading}
            />
            <button type="submit" disabled={loading || !input.trim()}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 text-white px-6 rounded-xl font-medium">
              Send
            </button>
          </div>
        </form>
      </main>
    </>
  );
}
