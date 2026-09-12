"use client";

import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

export function ExpandableText({
  text,
  secondaryText,
  className = "",
  secondaryClassName = "",
  threshold = 28,
}: {
  text: string;
  secondaryText?: string | null;
  className?: string;
  secondaryClassName?: string;
  threshold?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();
  const canExpand = text.length > threshold || (secondaryText?.length ?? 0) > threshold;

  return (
    <div className="min-w-0">
      <p
        id={contentId}
        className={`long-data-text ${expanded ? "" : "line-clamp-2"} ${className}`}
        title={text}
      >
        {text}
      </p>
      {secondaryText ? (
        <p
          className={`long-data-text mt-1 ${expanded ? "" : "truncate"} ${secondaryClassName}`}
          title={secondaryText}
        >
          {secondaryText}
        </p>
      ) : null}
      {canExpand ? (
        <button
          type="button"
          className="mt-1.5 inline-flex min-h-7 items-center gap-1 rounded-md px-1.5 text-[11px] font-semibold text-[var(--accent-strong)] transition hover:bg-[var(--accent-soft)]"
          aria-controls={contentId}
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "收起" : "展开全文"}
          <ChevronDown className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </button>
      ) : null}
    </div>
  );
}
