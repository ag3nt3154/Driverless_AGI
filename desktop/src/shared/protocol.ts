/**
 * Shared protocol types and Zod validators for the NDJSON sidecar protocol.
 * Every command sent to Python and every event received from Python must
 * conform to these schemas.
 */

import { z } from "zod";

// ── Protocol version ──────────────────────────────────────────────────────────

export const PROTOCOL_VERSION = 1;

// ── Outbound commands (Electron → Python) ─────────────────────────────────────

const BaseCommand = z.object({
  version: z.literal(PROTOCOL_VERSION),
  id: z.string().min(1),
});

export const RunCommand = BaseCommand.extend({
  type: z.literal("run"),
  task: z.string(),
});

export const CancelCommand = BaseCommand.extend({
  type: z.literal("cancel"),
});

export const PauseCommand = BaseCommand.extend({
  type: z.literal("pause"),
});

export const ResumeCommand = BaseCommand.extend({
  type: z.literal("resume"),
  message: z.string().default(""),
});

export const AnswerQuestionCommand = BaseCommand.extend({
  type: z.literal("answer_question"),
  question_id: z.string(),
  answer: z.string(),
});

export const CompactCommand = BaseCommand.extend({
  type: z.literal("compact"),
});

export const ClearCommand = BaseCommand.extend({
  type: z.literal("clear"),
});

export const SetModelCommand = BaseCommand.extend({
  type: z.literal("set_model"),
  model_id: z.string(),
});

export const SetProjectCommand = BaseCommand.extend({
  type: z.literal("set_project"),
  project_path: z.string(),
});

export const ListToolsCommand = BaseCommand.extend({
  type: z.literal("list_tools"),
});

export const ListSkillsCommand = BaseCommand.extend({
  type: z.literal("list_skills"),
});

export const ListWorkflowsCommand = BaseCommand.extend({
  type: z.literal("list_workflows"),
});

export const InvokeSkillCommand = BaseCommand.extend({
  type: z.literal("invoke_skill"),
  skill_name: z.string(),
  args: z.string().optional(),
});

export const InvokeWorkflowCommand = BaseCommand.extend({
  type: z.literal("invoke_workflow"),
  workflow_name: z.string(),
  args: z.string().optional(),
});

export const ListHistoryCommand = BaseCommand.extend({
  type: z.literal("list_history"),
});

export const RestoreHistoryCommand = BaseCommand.extend({
  type: z.literal("restore_history"),
  session_path: z.string(),
  turn_index: z.number().int().nonnegative().optional(),
});

export const InitializeProjectCommand = BaseCommand.extend({
  type: z.literal("initialize_project"),
  project_path: z.string(),
});

export const InitializeCommand = BaseCommand.extend({
  type: z.literal("initialize"),
});

export const ShutdownCommand = BaseCommand.extend({
  type: z.literal("shutdown"),
});

export const AnyCommand = z.discriminatedUnion("type", [
  RunCommand,
  CancelCommand,
  PauseCommand,
  ResumeCommand,
  AnswerQuestionCommand,
  CompactCommand,
  ClearCommand,
  SetModelCommand,
  SetProjectCommand,
  ListToolsCommand,
  ListSkillsCommand,
  ListWorkflowsCommand,
  InvokeSkillCommand,
  InvokeWorkflowCommand,
  ListHistoryCommand,
  RestoreHistoryCommand,
  InitializeProjectCommand,
  InitializeCommand,
  ShutdownCommand,
]);

export type Command = z.infer<typeof AnyCommand>;
export type RunCommandType = z.infer<typeof RunCommand>;
export type ResumeCommandType = z.infer<typeof ResumeCommand>;

// ── Inbound events (Python → Electron) ───────────────────────────────────────

const BaseEvent = z.object({
  version: z.literal(PROTOCOL_VERSION),
});

export const ReadyEvent = BaseEvent.extend({ type: z.literal("ready") });
export const AckEvent = BaseEvent.extend({
  type: z.literal("ack"),
  request_id: z.string(),
  result: z.record(z.unknown()).optional(),
});
export const CommandErrorEvent = BaseEvent.extend({
  type: z.literal("command_error"),
  request_id: z.string().optional(),
  message: z.string(),
});
export const ErrorEvent = BaseEvent.extend({
  type: z.literal("error"),
  message: z.string(),
});
export const ShutdownCompleteEvent = BaseEvent.extend({
  type: z.literal("shutdown_complete"),
});

// Agent progress events
export const TokenEvent = BaseEvent.extend({
  type: z.literal("token"),
  text: z.string(),
});
export const ThinkingEvent = BaseEvent.extend({
  type: z.literal("thinking"),
  text: z.string(),
});
export const ToolCallEvent = BaseEvent.extend({
  type: z.literal("tool_call"),
  tool: z.string(),
  input: z.record(z.unknown()),
  call_id: z.string().optional(),
});
export const ToolResultEvent = BaseEvent.extend({
  type: z.literal("tool_result"),
  tool: z.string(),
  content: z.string(),
  call_id: z.string().optional(),
  is_error: z.boolean().optional(),
});
export const TurnStartEvent = BaseEvent.extend({
  type: z.literal("turn_start"),
  turn: z.number(),
});
export const TurnEndEvent = BaseEvent.extend({
  type: z.literal("turn_end"),
  turn: z.number(),
  usage: z.record(z.unknown()).optional(),
});
export const TaskCompleteEvent = BaseEvent.extend({
  type: z.literal("task_complete"),
  result: z.string(),
});
export const CompactEvent = BaseEvent.extend({
  type: z.literal("compact"),
  summary: z.string(),
});
export const QuestionEvent = BaseEvent.extend({
  type: z.literal("question"),
  question_id: z.string(),
  text: z.string(),
  options: z.array(z.string()).optional(),
});
export const SubagentEvent = BaseEvent.extend({
  type: z.literal("subagent"),
  content: z.record(z.unknown()),
});
export const PlanUpdateEvent = BaseEvent.extend({
  type: z.literal("plan_update"),
  content: z.string(),
});
export const CostUpdateEvent = BaseEvent.extend({
  type: z.literal("cost_update"),
  total_usd: z.number(),
  session_tokens: z.number().optional(),
});

export const AnyEvent = z.discriminatedUnion("type", [
  ReadyEvent,
  AckEvent,
  CommandErrorEvent,
  ErrorEvent,
  ShutdownCompleteEvent,
  TokenEvent,
  ThinkingEvent,
  ToolCallEvent,
  ToolResultEvent,
  TurnStartEvent,
  TurnEndEvent,
  TaskCompleteEvent,
  CompactEvent,
  QuestionEvent,
  SubagentEvent,
  PlanUpdateEvent,
  CostUpdateEvent,
]);

export type SidecarEvent = z.infer<typeof AnyEvent>;
export type AckEventType = z.infer<typeof AckEvent>;
export type QuestionEventType = z.infer<typeof QuestionEvent>;
export type ToolCallEventType = z.infer<typeof ToolCallEvent>;
export type ToolResultEventType = z.infer<typeof ToolResultEvent>;

// ── Helpers ───────────────────────────────────────────────────────────────────

let _cmdCounter = 0;

/** Generate a unique command id. */
export function makeCommandId(): string {
  return `cmd-${++_cmdCounter}-${Date.now()}`;
}

/** Serialize a command to an NDJSON line. */
export function serializeCommand(
  type: Command["type"],
  extras: Record<string, unknown> = {}
): string {
  const cmd = { version: PROTOCOL_VERSION, id: makeCommandId(), type, ...extras };
  return JSON.stringify(cmd);
}

/** Parse and validate an inbound NDJSON event line. Returns null on failure. */
export function parseEvent(line: string): SidecarEvent | null {
  try {
    const raw = JSON.parse(line);
    return AnyEvent.parse(raw);
  } catch {
    return null;
  }
}
