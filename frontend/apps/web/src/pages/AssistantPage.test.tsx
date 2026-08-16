import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AssistantPage } from './AssistantPage';
import { api } from '../api';
import type { AssistantStreamEvent } from '../types';

vi.mock('../api', () => ({
  api: {
    streamAssistantAsk: vi.fn(),
  },
}));

async function* streamOf(...events: AssistantStreamEvent[]) {
  for (const e of events) yield e;
}

const BASE_RESULT = {
  persona: 'risk_analyst', question: 'q?', answer: 'the answer', provider: 'ollama',
  turns: 1, partial: false, roles: [], effective_tools: [], tool_calls: [],
  history: [{ role: 'user' as const, content: 'q?' }, { role: 'assistant' as const, content: 'the answer' }],
};

afterEach(() => vi.resetAllMocks());

describe('AssistantPage', () => {
  it('renders the persona picker and question box', () => {
    render(<AssistantPage />);
    expect(screen.getByText('Risk Analyst')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Ask a question in plain English…')).toBeInTheDocument();
  });

  it('streams live tool-call progress and renders the final result', async () => {
    vi.mocked(api.streamAssistantAsk).mockReturnValue(streamOf(
      { event: 'tool_call', data: { name: 'get_bank_xray', input: { cert: 1 } } },
      { event: 'tool_result', data: { name: 'get_bank_xray', preview: 'CET1 12.5%', citation_url: '/bank/1' } },
      { event: 'final', data: 'the answer' },
      { event: 'result', data: BASE_RESULT },
    ));
    const user = userEvent.setup();
    render(<AssistantPage />);
    await user.type(screen.getByPlaceholderText('Ask a question in plain English…'), 'how risky?');
    await user.click(screen.getByRole('button', { name: /ask/i }));

    expect(await screen.findByText('the answer')).toBeInTheDocument();
    expect(screen.getByText(/ollama/)).toBeInTheDocument();
    expect(api.streamAssistantAsk).toHaveBeenCalledWith('risk_analyst', 'how risky?', []);
  });

  it('shows a partial-answer banner when the server deadline was reached', async () => {
    vi.mocked(api.streamAssistantAsk).mockReturnValue(streamOf(
      { event: 'timeout', data: { message: 'exceeded the 120s deadline' } },
      { event: 'result', data: { ...BASE_RESULT, partial: true, answer: '(partial data)' } },
    ));
    const user = userEvent.setup();
    render(<AssistantPage />);
    await user.type(screen.getByPlaceholderText('Ask a question in plain English…'), 'slow question');
    await user.click(screen.getByRole('button', { name: /ask/i }));

    expect(await screen.findByText(/Partial answer/)).toBeInTheDocument();
    expect(screen.getByText('(partial data)')).toBeInTheDocument();
  });

  it('renders an error banner instead of crashing when the stream errors out', async () => {
    vi.mocked(api.streamAssistantAsk).mockReturnValue(streamOf(
      { event: 'error', data: { error: 'provider did not respond to cancellation' } },
    ));
    const user = userEvent.setup();
    render(<AssistantPage />);
    await user.type(screen.getByPlaceholderText('Ask a question in plain English…'), 'hung question');
    await user.click(screen.getByRole('button', { name: /ask/i }));

    expect(await screen.findByText('provider did not respond to cancellation')).toBeInTheDocument();
  });
});
