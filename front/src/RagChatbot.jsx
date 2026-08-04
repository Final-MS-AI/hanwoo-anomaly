import { useEffect, useRef, useState } from "react";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

const RAG_API_URL =
  import.meta.env.VITE_RAG_API_URL || `${API_BASE_URL}/rag/chat`;

const suggestedQuestions = [
  "장시간 누워 있는 소는 어떻게 확인하나요?",
  "주의 개체와 위험 개체의 차이가 뭔가요?",
  "귀표 등록 절차를 알려줘",
];

function normalizeSources(data) {
  const sources = data?.sources ?? data?.references ?? data?.citations ?? [];

  return sources.map((source, index) => {
    if (typeof source === "string") {
      return { id: `${index}-${source}`, title: source };
    }

    return {
      id: source.id ?? `${index}-${source.title ?? source.name ?? "source"}`,
      title: source.title ?? source.name ?? source.document ?? `출처 ${index + 1}`,
      page: source.page ?? source.page_number ?? null,
    };
  });
}

function RagChatbot() {
  const [messages, setMessages] = useState([
    {
      id: "welcome",
      role: "assistant",
      content:
        "한우 사육·이상 행동·서비스 사용법을 문서 근거와 함께 안내해 드립니다.",
      sources: [],
    },
  ]);
  const [question, setQuestion] = useState("");
  const [isSending, setIsSending] = useState(false);
  const messageEndRef = useRef(null);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  const sendQuestion = async (questionText) => {
    const trimmedQuestion = questionText.trim();

    if (!trimmedQuestion || isSending) {
      return;
    }

    const userMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmedQuestion,
      sources: [],
    };

    setMessages((previous) => [...previous, userMessage]);
    setQuestion("");
    setIsSending(true);

    try {
      const response = await fetch(RAG_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: trimmedQuestion,
          messages: messages.map(({ role, content }) => ({ role, content })),
        }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? data.message ?? "답변 생성에 실패했습니다.");
      }

      setMessages((previous) => [
        ...previous,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: data.answer ?? data.message ?? data.content ?? "답변이 비어 있습니다.",
          sources: normalizeSources(data),
        },
      ]);
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: `RAG 서버에 연결하지 못했습니다. ${error.message}`,
          sources: [],
          isError: true,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    sendQuestion(question);
  };

  return (
    <section className="rag-chat-page">
      <div className="rag-chat-header">
        <div>
          <span className="rag-status"><i /> 문서 기반 답변</span>
          <h2>한우 AI 상담</h2>
          <p>등록된 사육 지침과 서비스 문서를 검색해 답변합니다.</p>
        </div>
        <span className="rag-badge">RAG</span>
      </div>

      <div className="rag-message-list" aria-live="polite">
        {messages.map((message) => (
          <article
            className={`rag-message ${message.role} ${message.isError ? "error" : ""}`}
            key={message.id}
          >
            <span className="rag-message-author">
              {message.role === "assistant" ? "COWOW AI" : "나"}
            </span>
            <p>{message.content}</p>

            {message.sources.length > 0 && (
              <div className="rag-sources">
                <strong>참고 문서</strong>
                {message.sources.map((source) => (
                  <span key={source.id}>
                    {source.title}{source.page ? ` · ${source.page}쪽` : ""}
                  </span>
                ))}
              </div>
            )}
          </article>
        ))}

        {isSending && (
          <div className="rag-typing" aria-label="답변 생성 중">
            <span /><span /><span />
          </div>
        )}
        <div ref={messageEndRef} />
      </div>

      {messages.length === 1 && (
        <div className="rag-suggestions">
          {suggestedQuestions.map((suggestion) => (
            <button
              type="button"
              key={suggestion}
              onClick={() => sendQuestion(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <form className="rag-chat-form" onSubmit={handleSubmit}>
        <label htmlFor="rag-question" className="sr-only">질문 입력</label>
        <textarea
          id="rag-question"
          rows="1"
          value={question}
          placeholder="한우 관리에 대해 질문하세요"
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSubmit(event);
            }
          }}
        />
        <button type="submit" disabled={!question.trim() || isSending}>
          전송
        </button>
      </form>
      <p className="rag-disclaimer">AI 답변은 참고용이며, 긴급한 건강 문제는 수의사에게 확인하세요.</p>
    </section>
  );
}

export default RagChatbot;
