"use client";

import type { ReactNode } from "react";
import { answerParts, citationId } from "@/lib/citations";
import { replyTableAt } from "@/lib/replyTables";
import type { Citation } from "@/lib/types";

// Render common reply formatting as React elements; never inject model HTML.
export default function MessageContent({ text, citations, onCitation }: {
  text: string;
  citations: Citation[];
  onCitation: (id: string) => void;
}) {
  const inline = (value: string): ReactNode => answerParts(value, citations).map((part, index) => {
    if (part.citation) return <button key={index} type="button" className="reply-citation" title="查看引用原文" onClick={() => onCitation(citationId(part.citation!))}>{part.text}</button>;
    return <span key={index}>{part.text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((piece, i) => piece.startsWith("**") && piece.endsWith("**") ? <strong key={i}>{piece.slice(2, -2)}</strong> : piece.startsWith("`") && piece.endsWith("`") ? <code key={i}>{piece.slice(1, -1)}</code> : piece)}</span>;
  });

  const lines = text.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const key = index;
    if (!line.trim()) { index++; continue; }
    if (/^\s*```/.test(line)) {
      const language = line.trim().slice(3);
      const code: string[] = [];
      index++;
      while (index < lines.length && !/^\s*```/.test(lines[index])) code.push(lines[index++]);
      if (index < lines.length) index++;
      blocks.push(<div key={key} className="reply-code">{language ? <div className="reply-code-label">{language}</div> : null}<pre><code>{code.join("\n")}</code></pre></div>);
      continue;
    }
    const table = replyTableAt(lines, index);
    if (table) {
      blocks.push(
        <div key={key} className="reply-table-scroll" role="region" aria-label="回复数据表格" tabIndex={0}>
          <table className="reply-table">
            <thead><tr>{table.headers.map((header, column) =>
              <th key={column} scope="col" style={{ textAlign: table.alignments[column] }}>{inline(header)}</th>
            )}</tr></thead>
            <tbody>{table.rows.map((row, rowIndex) =>
              <tr key={rowIndex}>{row.map((cell, column) =>
                <td key={column} style={{ textAlign: table.alignments[column] }}>{inline(cell)}</td>
              )}</tr>
            )}</tbody>
          </table>
        </div>
      );
      index = table.nextLine;
      continue;
    }
    const heading = line.match(/^#{1,6}\s+(.+)/);
    if (heading) { blocks.push(<h3 key={key}>{inline(heading[1])}</h3>); index++; continue; }
    const list = line.match(/^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)/);
    if (list) {
      const ordered = /^\s*\d/.test(line);
      const start = ordered ? parseInt(line.trim(), 10) : undefined;
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const item = lines[index].match(ordered ? /^\s*\d+[.)]\s+(.*)/ : /^\s*[-*+]\s+(.*)/);
        if (!item) break;
        items.push(<li key={index}>{inline(item[1])}</li>);
        index++;
      }
      blocks.push(ordered ? <ol key={key} start={start}>{items}</ol> : <ul key={key}>{items}</ul>);
      continue;
    }
    const paragraph = [line];
    index++;
    while (index < lines.length && lines[index].trim() && !replyTableAt(lines, index) && !/^\s*(?:```|#{1,6}\s|[-*+]\s|\d+[.)]\s)/.test(lines[index])) paragraph.push(lines[index++]);
    blocks.push(<p key={key}>{inline(paragraph.join("\n"))}</p>);
  }
  return <div className="reply-content">{blocks}</div>;
}
