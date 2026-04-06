import { useState, useRef, useEffect } from 'react';
import { sendChat } from '../utils/api';

export default function Chat() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Hello! I can help you explore and manage your topology. Try asking:\n- "How many queue managers?"\n- "Where does app 8A live?"\n- "What are the communities?"\n- "What\'s the complexity score?"' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [useLLM, setUseLLM] = useState(false);
  const endRef = useRef();

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const msg = input.trim();
    if (!msg || loading) return;

    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: msg }]);
    setLoading(true);

    try {
      const res = await sendChat(msg, useLLM);
      setMessages((prev) => [...prev, { role: 'assistant', content: res.response, llm: useLLM }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'assistant', content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto flex flex-col h-[calc(100vh-200px)]">
      <div className="flex-1 overflow-y-auto space-y-4 pb-4">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-indigo-600 text-white rounded-br-md'
                  : 'bg-gray-800 text-gray-200 border border-gray-700 rounded-bl-md'
              }`}
            >
              {m.content}
              {m.role === 'assistant' && i > 0 && (
                <div className="mt-1.5 text-[10px] text-gray-600">
                  {m.llm ? 'via LLM' : 'local analysis'}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-800 border border-gray-700 text-gray-400 px-4 py-3 rounded-2xl rounded-bl-md text-sm">
              {useLLM ? 'Thinking with LLM...' : 'Analyzing...'}
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="border-t border-gray-800 pt-4">
        {/* LLM Toggle */}
        <div className="flex items-center gap-3 mb-3">
          <button
            onClick={() => setUseLLM(false)}
            className={`px-3 py-1.5 text-xs rounded-lg transition ${!useLLM ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}
          >
            Local Analysis
          </button>
          <button
            onClick={() => setUseLLM(true)}
            className={`px-3 py-1.5 text-xs rounded-lg transition ${useLLM ? 'bg-emerald-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-gray-200'}`}
          >
            With LLM
          </button>
          <span className="text-[10px] text-gray-600">
            {useLLM ? 'Uses Ollama/Claude for open-ended reasoning' : 'Fast pattern-matched answers from topology data'}
          </span>
        </div>
        {/* Input */}
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Ask about your topology..."
            className="flex-1 px-4 py-3 bg-gray-800 border border-gray-700 rounded-xl text-sm text-white focus:border-indigo-500 focus:outline-none"
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm transition disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
