import { FormEvent, useEffect, useRef, useState } from "react";
import { useChat } from "../hooks/useChat";
import { JobProgress } from "../components/JobProgress";
import { ChatText } from "../components/ChatText";

export function ChatAssistant() {
  const { messages, sendMessage, sending } = useChat();
  const [draft, setDraft] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    await sendMessage(text);
  }

  return (
    <div className="chat-shell">
      <header className="page-header">
        <div className="eyebrow">AI assistant</div>
        <h1>Sourcing chat</h1>
        <p>
          Describe who you're looking for. I'll run the LinkedIn + Google searcher crew and a
          reviewer agent shortlists the results — ask follow-ups about anything it finds.
        </p>
      </header>

      <div className="chat-transcript" ref={transcriptRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            Try: "Find a founding engineer in Bangalore, strong in TypeScript and AWS."
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`chat-msg ${m.role}`}>
            <ChatText text={m.text} />
            {m.pendingJobIds?.map((jobId) => (
              <div className="chat-msg-job" key={jobId}>
                <JobProgress jobId={jobId} />
              </div>
            ))}
          </div>
        ))}
        {sending && <div className="chat-msg assistant progress-message">Thinking…</div>}
      </div>

      <form className="chat-input-row" onSubmit={handleSubmit}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit(e);
            }
          }}
          placeholder="Ask for candidates, a profile lookup, or a company search…"
        />
        <button type="submit" className="btn btn-primary" disabled={sending || !draft.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
