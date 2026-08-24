import { useCallback, useRef, useState } from "react";
import { getJob, reportJobResult, sendChatMessage } from "../api/client";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  text: string;
  pendingJobIds?: string[];
}

const POLL_MS = 1500;

function uid(): string {
  return Math.random().toString(36).slice(2);
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const conversationIdRef = useRef<string | null>(null);
  const watchedJobs = useRef<Set<string>>(new Set());

  const appendAssistantTurn = useCallback((text: string, pendingJobIds: string[]) => {
    setMessages((m) => [...m, { id: uid(), role: "assistant", text, pendingJobIds }]);
    pendingJobIds.forEach((jobId) => watchJob(jobId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function watchJob(jobId: string) {
    if (watchedJobs.current.has(jobId)) return;
    watchedJobs.current.add(jobId);

    const poll = async () => {
      try {
        const job = await getJob(jobId);
        if (job.status === "succeeded" || job.status === "failed") {
          const conversationId = conversationIdRef.current;
          if (!conversationId) return;
          const result = await reportJobResult(conversationId, jobId);
          appendAssistantTurn(result.text, result.pending_job_ids);
          return;
        }
      } catch {
        // transient - keep polling
      }
      setTimeout(poll, POLL_MS);
    };
    poll();
  }

  const sendMessage = useCallback(
    async (text: string) => {
      setMessages((m) => [...m, { id: uid(), role: "user", text }]);
      setSending(true);
      try {
        const result = await sendChatMessage(conversationIdRef.current, text);
        conversationIdRef.current = result.conversation_id;
        appendAssistantTurn(result.text, result.pending_job_ids);
      } catch (err) {
        setMessages((m) => [
          ...m,
          { id: uid(), role: "error", text: err instanceof Error ? err.message : String(err) },
        ]);
      } finally {
        setSending(false);
      }
    },
    [appendAssistantTurn]
  );

  return { messages, sendMessage, sending };
}
