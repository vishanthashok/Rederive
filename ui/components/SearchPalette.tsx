"use client";

import { CommandDialog, CommandGroup, CommandItem } from "@/components/ui/command";
import { StatusBadge } from "@/components/ui/status-badge";
import { label, type GraphNode } from "@/lib/api";

export default function SearchPalette({
  open,
  onOpenChange,
  nodes,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nodes: GraphNode[];
  onSelect: (id: string) => void;
}) {
  const byKind = new Map<string, GraphNode[]>();
  nodes.forEach((n) => byKind.set(n.kind, [...(byKind.get(n.kind) ?? []), n]));
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} placeholder="Search records by name, text, or id…">
      {[...byKind.entries()].map(([kind, recs]) => (
        <CommandGroup
          key={kind}
          heading={kind}
          className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted"
        >
          {recs.map((n) => (
            <CommandItem
              key={n.id}
              value={`${label(n)} ${n.text} ${n.id}`}
              onSelect={() => {
                onSelect(n.id);
                onOpenChange(false);
              }}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm data-[selected=true]:bg-bg"
            >
              <StatusBadge status={n.status} />
              <span className="shrink-0 font-medium">{label(n)}</span>
              <span className="truncate text-xs text-muted">{n.text}</span>
            </CommandItem>
          ))}
        </CommandGroup>
      ))}
    </CommandDialog>
  );
}
