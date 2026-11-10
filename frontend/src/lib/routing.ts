/** Presentation helpers for Chris's routing result (the registry's expert selection). */
import type { RoutingInfo } from './api';

/** Plain-language explanations for the error codes Chris and the registry report.
 * Unknown codes fall back to a generic sentence; the raw code is always shown too. */
const ERROR_TEXT: Record<string, string> = {
  registry_timeout: 'The registry took too long to answer.',
  registry_unreachable: 'The registry could not be reached. Is it running?',
  registry_auth_rejected: 'The registry refused this request (authentication).',
  registry_protocol_error: 'The registry answered in a way Chris could not use.',
  registry_invalid_reply: 'The registry sent a reply that does not match its contract, so it was not trusted.',
  registry_not_configured: 'Chris is not configured with a valid registry address.',
  selection_unavailable: 'The registry could not reach its selection model.',
  selection_busy: 'The registry is busy with other selections. Try again shortly.',
  invalid_model_reply: 'The registry’s model gave an unusable reply.',
  agent_unavailable: 'The chosen expert stopped being available while the registry was deciding.',
  registry_capacity_exceeded: 'More experts are registered than the registry can choose between.',
  registry_unavailable: 'The registry could not read its list of experts.',
  not_configured: 'The registry’s model is not configured.',
  invalid_request: 'The registry could not accept this question.',
  internal_error: 'The registry hit an unexpected problem.'
};

export function describeError(code: string): string {
  return ERROR_TEXT[code] ?? 'The registry could not select an expert.';
}

export function confidenceLabel(confidence: number | null): string | null {
  return confidence === null ? null : `${Math.round(confidence * 100)}% confident`;
}

/** One-line status for screen readers and the card heading. */
export function headline(routing: RoutingInfo): string {
  if (routing.status === 'selected' && routing.agent) return `Expert selected: ${routing.agent.name}`;
  if (routing.status === 'no_match') return 'No matching expert';
  return 'Could not select an expert';
}
