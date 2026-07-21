import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function MarkdownContent({ value, compact = false }: { value: string; compact?: boolean }) {
  return <div className={compact ? "markdown-content compact" : "markdown-content"}>
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
  </div>;
}
