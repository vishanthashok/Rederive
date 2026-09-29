"use client";

import * as AD from "@radix-ui/react-alert-dialog";
import type { ReactNode } from "react";
import { Button } from "./button";

/** A confirm dialog. `trigger` opens it, `onConfirm` runs on the confirm button. */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  onConfirm,
}: {
  trigger: ReactNode;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
}) {
  return (
    <AD.Root>
      <AD.Trigger asChild>{trigger}</AD.Trigger>
      <AD.Portal>
        <AD.Overlay className="fixed inset-0 z-50 bg-black/40 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <AD.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-32px)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-panel p-5 shadow-xl data-[state=open]:animate-in data-[state=open]:zoom-in-95">
          <AD.Title className="text-base font-semibold">{title}</AD.Title>
          <AD.Description asChild>
            <div className="mt-2 text-sm text-muted">{description}</div>
          </AD.Description>
          <div className="mt-5 flex justify-end gap-2">
            <AD.Cancel asChild>
              <Button>Cancel</Button>
            </AD.Cancel>
            <AD.Action asChild>
              <Button variant="solidDanger" onClick={onConfirm}>
                {confirmLabel}
              </Button>
            </AD.Action>
          </div>
        </AD.Content>
      </AD.Portal>
    </AD.Root>
  );
}
