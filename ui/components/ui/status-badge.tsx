import type { Status } from "@/lib/api";
import { STATUS } from "@/lib/status";
import { cn } from "@/lib/utils";

export function StatusBadge({ status, className, children }: { status: Status; className?: string; children?: React.ReactNode }) {
  const s = STATUS[status] ?? STATUS.valid;
  const Icon = s.icon;
  return (
    <span
      className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-px text-[11px] lowercase", className)}
      style={{ color: s.color, borderColor: s.color }}
    >
      <Icon aria-hidden className={cn("size-3", status === "rebuilding" && "animate-spin")} />
      {children ?? s.label}
    </span>
  );
}
