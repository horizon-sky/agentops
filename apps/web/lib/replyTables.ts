export interface ReplyTable {
  headers: string[];
  alignments: Array<"left" | "center" | "right">;
  rows: string[][];
  nextLine: number;
}

function cells(line: string): string[] {
  const tokens = line.trim().match(/\\.|\||[^\\|]+|\\$/g) ?? [];
  if (tokens[0] === "|") tokens.shift();
  if (tokens[tokens.length - 1] === "|") tokens.pop();
  const result = [""];
  for (const token of tokens) {
    if (token === "|") result.push("");
    else result[result.length - 1] += token === "\\|" ? "|" : token;
  }
  return result.map(cell => cell.trim());
}

export function replyTableAt(lines: string[], start: number): ReplyTable | null {
  if (!lines[start]?.includes("|") || !lines[start + 1]?.includes("|")) return null;
  const headers = cells(lines[start]);
  const separators = cells(lines[start + 1]);
  if (headers.length !== separators.length || !separators.every(cell => /^:?-+:?$/.test(cell))) {
    return null;
  }
  const alignments: ReplyTable["alignments"] = separators.map(cell =>
    cell.endsWith(":") ? (cell.startsWith(":") ? "center" : "right") : "left"
  );
  const rows: string[][] = [];
  let nextLine = start + 2;
  while (nextLine < lines.length && lines[nextLine].trim() && lines[nextLine].includes("|")) {
    if (/^\s*(?:```|#{1,6}\s|[-*+]\s|\d+[.)]\s)/.test(lines[nextLine])) break;
    const row = cells(lines[nextLine++]);
    rows.push(headers.map((_, column) => row[column] ?? ""));
  }
  return { headers, alignments, rows, nextLine };
}
