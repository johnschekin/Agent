/**
 * Lightweight DSL tokenizer for syntax highlighting.
 *
 * This is NOT a parser — the backend is the single source of truth for parsing.
 * This module only produces token spans for coloring in the UI.
 */

export type DslTokenType =
  | "field"       // heading:, clause:, meta:
  | "operator"    // |, &, !, /N (proximity)
  | "string"      // "quoted value"
  | "regex"       // /pattern/
  | "macro"       // @macro_name
  | "keyword"     // reserved: AND, OR, NOT, NEAR
  | "paren"       // ( )
  | "whitespace"
  | "plain";      // everything else

export interface DslToken {
  type: DslTokenType;
  text: string;
  start: number;
  end: number;
}

// Field names recognized by the DSL — must match backend ALL_FIELDS
const FIELD_NAMES = new Set([
  "heading", "clause", "section", "article", "defined_term",
  "template", "vintage", "market", "doc_type", "admin_agent", "facility_size_mm",
]);

// Reserved keyword pattern
const KEYWORDS = new Set(["AND", "OR", "NOT", "NEAR"]);

/**
 * Tokenize a DSL text string into highlighted spans.
 * Returns an array of non-overlapping tokens covering the full input.
 */
export function tokenizeDsl(text: string): DslToken[] {
  if (!text) return [];
  const tokens: DslToken[] = [];
  let pos = 0;

  while (pos < text.length) {
    // Whitespace
    const wsMatch = text.slice(pos).match(/^\s+/);
    if (wsMatch) {
      tokens.push({
        type: "whitespace",
        text: wsMatch[0],
        start: pos,
        end: pos + wsMatch[0].length,
      });
      pos += wsMatch[0].length;
      continue;
    }

    // Field name (word followed by colon)
    const fieldMatch = text.slice(pos).match(/^(\w+):/);
    if (fieldMatch && FIELD_NAMES.has(fieldMatch[1].toLowerCase())) {
      tokens.push({
        type: "field",
        text: fieldMatch[0],
        start: pos,
        end: pos + fieldMatch[0].length,
      });
      pos += fieldMatch[0].length;
      continue;
    }

    // Macro reference (@name)
    const macroMatch = text.slice(pos).match(/^@\w+/);
    if (macroMatch) {
      tokens.push({
        type: "macro",
        text: macroMatch[0],
        start: pos,
        end: pos + macroMatch[0].length,
      });
      pos += macroMatch[0].length;
      continue;
    }

    // Double-quoted string
    if (text[pos] === '"') {
      let end = pos + 1;
      while (end < text.length && text[end] !== '"') {
        if (text[end] === '\\') end++; // skip escaped char
        end++;
      }
      if (end < text.length) end++; // consume closing quote
      tokens.push({
        type: "string",
        text: text.slice(pos, end),
        start: pos,
        end,
      });
      pos = end;
      continue;
    }

    // Single-quoted string
    if (text[pos] === "'") {
      let end = pos + 1;
      while (end < text.length && text[end] !== "'") {
        if (text[end] === '\\') end++;
        end++;
      }
      if (end < text.length) end++;
      tokens.push({
        type: "string",
        text: text.slice(pos, end),
        start: pos,
        end,
      });
      pos = end;
      continue;
    }

    // Regex literal /pattern/
    if (text[pos] === "/" && pos > 0 && !/\d/.test(text[pos + 1] || "")) {
      let end = pos + 1;
      while (end < text.length && text[end] !== "/") {
        if (text[end] === '\\') end++;
        end++;
      }
      if (end < text.length) end++;
      tokens.push({
        type: "regex",
        text: text.slice(pos, end),
        start: pos,
        end,
      });
      pos = end;
      continue;
    }

    // Proximity operator /N
    const proxMatch = text.slice(pos).match(/^\/\d+/);
    if (proxMatch) {
      tokens.push({
        type: "operator",
        text: proxMatch[0],
        start: pos,
        end: pos + proxMatch[0].length,
      });
      pos += proxMatch[0].length;
      continue;
    }

    // Operators: | & !
    if ("|&!".includes(text[pos])) {
      tokens.push({
        type: "operator",
        text: text[pos],
        start: pos,
        end: pos + 1,
      });
      pos++;
      continue;
    }

    // Parentheses
    if ("()".includes(text[pos])) {
      tokens.push({
        type: "paren",
        text: text[pos],
        start: pos,
        end: pos + 1,
      });
      pos++;
      continue;
    }

    // Keywords (AND, OR, NOT, NEAR) — must be word boundaries
    const wordMatch = text.slice(pos).match(/^[A-Za-z_]\w*/);
    if (wordMatch) {
      const word = wordMatch[0];
      const type = KEYWORDS.has(word.toUpperCase()) ? "keyword" : "plain";
      tokens.push({
        type,
        text: word,
        start: pos,
        end: pos + word.length,
      });
      pos += word.length;
      continue;
    }

    // Anything else: single character
    tokens.push({
      type: "plain",
      text: text[pos],
      start: pos,
      end: pos + 1,
    });
    pos++;
  }

  return tokens;
}

/**
 * CSS class names for each token type (for use in the highlight renderer).
 */
export const DSL_TOKEN_CLASSES: Record<DslTokenType, string> = {
  field: "text-accent-cyan font-semibold",
  operator: "text-accent-orange font-bold",
  string: "text-accent-green",
  regex: "text-accent-purple italic",
  macro: "text-accent-blue font-medium",
  keyword: "text-accent-orange font-semibold",
  paren: "text-text-secondary font-bold",
  whitespace: "",
  plain: "text-text-primary",
};
