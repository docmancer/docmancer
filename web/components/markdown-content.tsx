import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownContent({ value, compact = false }: { value: string; compact?: boolean }) {
  const markdown = expandWikilinks(value);
  return <div className={compact ? "markdown-content compact" : "markdown-content"}>
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={(url) => safeLink(url) ?? ""}
      components={{
        img: ({ alt }) => <span className="blocked-image">Remote image omitted{alt ? `: ${alt}` : ""}</span>,
        a: ({ href, children }) => {
          const safeHref = safeLink(href);
          if (!safeHref) return <span className="blocked-link">{children}</span>;
          if (safeHref.startsWith("docmancer://")) return <button type="button" className="memory-link" onClick={() => window.dispatchEvent(new CustomEvent("docmancer:open-memory", { detail: { address: safeHref } }))}>{children}</button>;
          const external = safeHref.startsWith("https://") || safeHref.startsWith("http://");
          return <a href={safeHref} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined}>{children}</a>;
        },
      }}
    >{markdown}</ReactMarkdown>
  </div>;
}

function expandWikilinks(value: string): string {
  return value.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_match, target: string, label?: string) => {
    const address = `docmancer://title/${encodeURIComponent(target.trim())}`;
    return `[${(label || target).trim()}](${address})`;
  });
}

function safeLink(value: string | undefined): string | null {
  if (!value) return null;
  if (value.startsWith("#") || value.startsWith("docmancer://")) return value;
  try {
    const protocol = new URL(value).protocol;
    return ["https:", "http:", "mailto:"].includes(protocol) ? value : null;
  } catch {
    return null;
  }
}
