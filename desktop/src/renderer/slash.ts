/**
 * Slash-command parser for the renderer.
 *
 * Parses typed input like "/compact", "/model claude-opus-4-7", "/clear".
 * Returns a SlashCommand if the input starts with "/", otherwise null.
 *
 * This runs purely in the renderer so the palette can show before the
 * command is sent to the sidecar.
 */

export type SlashCommandName =
  | "compact"
  | "clear"
  | "cancel"
  | "model"
  | "skill"
  | "workflow"
  | "history"
  | "help";

export interface SlashCommand {
  name: SlashCommandName;
  args: string;
}

export interface SlashDefinition {
  name: SlashCommandName;
  description: string;
  /** Whether a free-text argument is expected after the command name */
  takesArg: boolean;
}

export const SLASH_DEFINITIONS: SlashDefinition[] = [
  { name: "compact",  description: "Compress conversation history",          takesArg: false },
  { name: "clear",    description: "Clear conversation and start fresh",      takesArg: false },
  { name: "cancel",   description: "Cancel the current running task",         takesArg: false },
  { name: "model",    description: "Switch model (e.g. /model claude-opus-4-7)", takesArg: true },
  { name: "skill",    description: "Invoke a skill (e.g. /skill memory-query)",  takesArg: true },
  { name: "workflow", description: "Invoke a workflow",                       takesArg: true },
  { name: "history",  description: "Browse and restore session history",      takesArg: false },
  { name: "help",     description: "Show available slash commands",           takesArg: false },
];

const VALID_NAMES = new Set<string>(SLASH_DEFINITIONS.map((d) => d.name));

/**
 * Parse a raw composer input string into a SlashCommand.
 * Returns null if the input is not a slash command or the name is unknown.
 */
export function parseSlash(input: string): SlashCommand | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/")) return null;

  const withoutSlash = trimmed.slice(1);
  const spaceIdx = withoutSlash.indexOf(" ");
  const name = spaceIdx === -1 ? withoutSlash : withoutSlash.slice(0, spaceIdx);
  const args = spaceIdx === -1 ? "" : withoutSlash.slice(spaceIdx + 1).trim();

  if (!VALID_NAMES.has(name)) return null;

  return { name: name as SlashCommandName, args };
}

/**
 * Return definitions whose name starts with the typed prefix (after the slash).
 * Used to populate the command palette dropdown.
 */
export function matchingCommands(prefix: string): SlashDefinition[] {
  const lower = prefix.toLowerCase().replace(/^\//, "");
  return SLASH_DEFINITIONS.filter((d) => d.name.startsWith(lower));
}
